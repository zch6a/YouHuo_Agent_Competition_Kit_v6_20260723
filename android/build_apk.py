"""编出两个安卓 App：优活老人（com.youhuo.elder）、优活家人（com.youhuo.family）。

不用 Gradle、不用 Android Studio：只用 SDK 里的 aapt2 / d8 / zipalign / apksigner
加一套 JDK 17。两个 App 是同一份代码（android/src），区别只在资源：名字、图标、
打开哪一页（android/variants/<端>/res）。

    python android/build_apk.py                       # 默认连公网演示服务器
    python android/build_apk.py --base-url https://…  # 换服务器

放在哪儿（都在 D:，不进仓库）：
    D:\\youhuo_work\\android-sdk\\     build-tools 34.0.0 + platforms/android-34
                                     （官方源下载、按官方索引核对过 SHA-1）
    D:\\youhuo_work\\android_sign\\    签名钥匙和它的口令。**别删**：
                                     以后发新版必须用同一把钥匙签，否则手机上装不上去
                                     （要先卸载旧版，数据会没）。
    D:\\youhuo_work\\android_build\\   中间产物；成品在 out\\

路径都可以用环境变量改：YOUHUO_ANDROID_SDK / YOUHUO_JDK / YOUHUO_ANDROID_WORK /
YOUHUO_ANDROID_SIGN。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import ipaddress
from urllib.parse import urlparse
import os
import secrets
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SDK = Path(os.environ.get("YOUHUO_ANDROID_SDK", r"D:\youhuo_work\android-sdk"))
BT = SDK / "build-tools" / "34.0.0"
ANDROID_JAR = SDK / "platforms" / "android-34" / "android.jar"
JDK = Path(os.environ.get("YOUHUO_JDK", r"D:\DevEco\jdk17\jdk-17.0.20.1+1"))
WORK = Path(os.environ.get("YOUHUO_ANDROID_WORK", r"D:\youhuo_work\android_build"))
SIGN = Path(os.environ.get("YOUHUO_ANDROID_SIGN", r"D:\youhuo_work\android_sign"))

DEFAULT_BASE = "https://5fe522bb333c4ec4b789413de1b18992.sg2.agentos-app.run"
VARIANTS = {"elder": "com.youhuo.elder", "family": "com.youhuo.family", "app": "com.youhuo.app"}
VERSION_NAME = "2.0.1"
VERSION_CODE = 3
MIN_SDK = 24          # 安卓 7.0：覆盖几乎所有还在用的安卓手机
TARGET_SDK = 34


def source_digest() -> str:
    """android/ 下全部文件的摘要（与判据 `test_the_packages_were_built_from_the_current_android_source`
    同一算法：按相对路径排序；换行统一成 LF，免得 git 换行转换把它变成「源码改了」）。"""
    h = hashlib.sha256()
    for path in sorted((p for p in HERE.rglob("*") if p.is_file()),
                       key=lambda p: p.relative_to(HERE).as_posix()):
        h.update(path.relative_to(HERE).as_posix().encode("utf-8") + b"\0")
        h.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def run(cmd: list, *, secret: str | None = None, capture: bool = False) -> str:
    shown = " ".join(str(c) for c in cmd)
    if secret:
        shown = shown.replace(secret, "******")
    print("  $", shown[:220] + (" …" if len(shown) > 220 else ""), flush=True)
    proc = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        out = (proc.stdout + proc.stderr)
        if secret:
            out = out.replace(secret, "******")
        raise SystemExit(f"失败（退出码 {proc.returncode}）：\n{out[-3000:]}")
    return proc.stdout if capture else ""


def check_tools() -> None:
    need = [BT / "aapt2.exe", BT / "zipalign.exe", BT / "lib" / "d8.jar", BT / "lib" / "apksigner.jar",
            ANDROID_JAR, JDK / "bin" / "javac.exe", JDK / "bin" / "java.exe", JDK / "bin" / "keytool.exe"]
    missing = [str(p) for p in need if not p.exists()]
    if missing:
        raise SystemExit("缺工具：\n  " + "\n  ".join(missing))


def keystore() -> tuple[Path, str]:
    """签名钥匙：第一次生成，之后一直用同一把。口令只存在 D: 上那个文件里。"""
    SIGN.mkdir(parents=True, exist_ok=True)
    ks = SIGN / "youhuo-apps.jks"
    pw_file = SIGN / "keystore-password.txt"
    if not ks.exists():
        pw = secrets.token_urlsafe(18)
        pw_file.write_text(pw, encoding="ascii")
        run([JDK / "bin" / "keytool.exe", "-genkeypair", "-keystore", ks, "-alias", "youhuo",
             "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
             "-dname", "CN=YouHuo, OU=C4-AI Competition, O=YouHuo Team, C=CN",
             "-storepass", pw, "-keypass", pw], secret=pw)
        print(f"  生成了新的签名钥匙：{ks}（口令在 {pw_file.name}）")
    return ks, pw_file.read_text(encoding="ascii").strip()


def build(variant: str, base_url: str, ks: Path, pw: str, *, debug: bool = False, lan: bool = False) -> Path:
    """`debug=True`：可调试、允许明文 http（连电脑上的测试服务器用），产物名带 -debug，
    **不**复制进 static/download、**不**写构建记录——它永远不该发给手机。"""
    pkg = VARIANTS[variant]
    work = WORK / (variant + ("-debug" if debug else ""))
    if work.resolve().parent != WORK.resolve() or WORK.resolve() == Path(WORK.anchor):
        raise SystemExit('Unsafe build workspace path')
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    print(f"\n== {variant}（{pkg}{'，调试版' if debug else ''}）==", flush=True)

    # 1. 资源：共用的 + 这一端的（同名文件以这一端为准）
    res = work / "res"
    shutil.copytree(HERE / "res", res)
    shutil.copytree(HERE / "variants" / ("elder" if variant == "app" else variant) / "res", res, dirs_exist_ok=True)
    strings = res / "values" / "strings.xml"
    text = strings.read_text(encoding="utf-8").replace("@BASE_URL@", base_url.rstrip("/"))
    if variant == "app":
        text = text.replace('优活老人', '优活').replace('/elder2</string>', '/elder4?launch=1</string>')
    assert "@BASE_URL@" not in text
    strings.write_text(text, encoding="utf-8")

    # 2. 清单
    manifest = (HERE / "AndroidManifest.template.xml").read_text(encoding="utf-8")
    manifest = (manifest.replace("@PACKAGE@", pkg)
                .replace("@VERSION_CODE@", str(VERSION_CODE))
                .replace("@VERSION_NAME@", VERSION_NAME))
    assert "@" not in manifest.replace("@string/", "").replace("@mipmap/", "").replace("@style/", "")
    if debug:
        assert manifest.count('android:usesCleartextTraffic="false"') == 1
        manifest = manifest.replace('android:usesCleartextTraffic="false"',
                                    'android:usesCleartextTraffic="true"\n        android:debuggable="true"')
    if lan:
        address = urlparse(base_url).hostname
        (res / 'xml').mkdir(exist_ok=True)
        (res / 'xml' / 'network_security_config.xml').write_text(
            '<?xml version="1.0" encoding="utf-8"?><network-security-config>'
            '<base-config cleartextTrafficPermitted="false" />'
            '<domain-config cleartextTrafficPermitted="true"><domain includeSubdomains="false">'
            + address + '</domain></domain-config></network-security-config>', encoding='utf-8')
        manifest = manifest.replace('android:usesCleartextTraffic="false"',
            'android:usesCleartextTraffic="false" android:networkSecurityConfig="@xml/network_security_config"')
    (work / "AndroidManifest.xml").write_text(manifest, encoding="utf-8")

    # 3. 源码 + 版本号
    src = work / "src"
    shutil.copytree(HERE / "src", src)
    (src / "com" / "youhuo" / "app" / "BuildInfo.java").write_text(
        "package com.youhuo.app;\n\n/** 由 build_apk.py 生成。 */\nfinal class BuildInfo {\n"
        f'    static final String VERSION_NAME = "{VERSION_NAME}";\n\n'
        "    private BuildInfo() { }\n}\n", encoding="utf-8")

    # 4. aapt2：编资源、连成 base.apk、生成 R.java
    run([BT / "aapt2.exe", "compile", "--dir", res, "-o", work / "res.zip"])
    gen = work / "gen"
    gen.mkdir()
    run([BT / "aapt2.exe", "link", "-o", work / "base.apk", "-I", ANDROID_JAR,
         "--manifest", work / "AndroidManifest.xml", "--java", gen,
         "--custom-package", "com.youhuo.app",
         "--min-sdk-version", MIN_SDK, "--target-sdk-version", TARGET_SDK,
         "--version-code", VERSION_CODE, "--version-name", VERSION_NAME,
         work / "res.zip"])

    # 5. javac（Java 8 字节码，d8 负责把 lambda 等翻成安卓认的）
    classes = work / "classes"
    classes.mkdir()
    java = sorted(str(p) for p in src.rglob("*.java")) + sorted(str(p) for p in gen.rglob("*.java"))
    run([JDK / "bin" / "javac.exe", "-encoding", "UTF-8", "-source", "8", "-target", "8",
         "-bootclasspath", ANDROID_JAR, "-classpath", ANDROID_JAR, "-Xlint:-options",
         "-d", classes, *java])

    # 6. d8：class → classes.dex
    dex = work / "dex"
    dex.mkdir()
    run([JDK / "bin" / "java.exe", "-cp", BT / "lib" / "d8.jar", "com.android.tools.r8.D8",
         "--release", "--min-api", MIN_SDK, "--lib", ANDROID_JAR, "--output", dex,
         *sorted(str(p) for p in classes.rglob("*.class"))])

    # 7. 把 dex 放进去、对齐、签名
    unaligned = work / "unaligned.apk"
    shutil.copyfile(work / "base.apk", unaligned)
    with zipfile.ZipFile(unaligned, "a", compression=zipfile.ZIP_DEFLATED) as z:
        z.write(dex / "classes.dex", "classes.dex")
    aligned = work / "aligned.apk"
    run([BT / "zipalign.exe", "-f", "-p", "4", unaligned, aligned])
    out_dir = WORK / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"youhuo-{variant}{'-debug' if debug else ''}.apk"
    run([JDK / "bin" / "java.exe", "-jar", BT / "lib" / "apksigner.jar", "sign",
         "--ks", ks, "--ks-key-alias", "youhuo", "--ks-pass", f"pass:{pw}", "--key-pass", f"pass:{pw}",
         "--min-sdk-version", MIN_SDK, "--out", out, aligned], secret=pw)

    # 8. 自己验一遍：签名、对齐、清单里写的是什么
    run([BT / "zipalign.exe", "-c", "-p", "4", out])
    verify = run([JDK / "bin" / "java.exe", "-jar", BT / "lib" / "apksigner.jar", "verify",
                  "--verbose", out], capture=True)
    badging = run([BT / "aapt2.exe", "dump", "badging", out], capture=True)
    for line in verify.splitlines():
        if line.startswith("Verified using"):
            print("   ", line)
    for line in badging.splitlines():
        if line.startswith(("package:", "application-label:", "sdkVersion:", "targetSdkVersion:",
                            "uses-permission:", "launchable-activity:")):
            print("   ", line[:160])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default=DEFAULT_BASE, help="服务器地址（不带末尾斜杠）")
    ap.add_argument("--only", choices=sorted(VARIANTS), help="只编一个")
    ap.add_argument('--lan', action='store_true', help='同 Wi-Fi 测试包，仅放行指定私网 IPv4 的 HTTP')
    ap.add_argument("--no-copy", action="store_true",
                    help="不复制到 backend/static/download/（默认复制：服务器从那里发给手机，"
                         "网址是 /download/youhuo-elder.apk、/download/youhuo-family.apk）")
    ap.add_argument("--debug-local", metavar="URL",
                    help="编调试版连电脑上的测试服务器（模拟器里电脑是 http://10.0.2.2:端口）。"
                         "可调试、允许明文 http；不复制、不写构建记录")
    args = ap.parse_args()
    check_tools()
    ks, pw = keystore()
    if args.debug_local:
        built = [build(v, args.debug_local, ks, pw, debug=True)
                 for v in VARIANTS if not args.only or v == args.only]
        print("\n调试版（只给模拟器用，别发给手机）：")
        for p in built:
            print(f"  {p}  {p.stat().st_size:,} B")
        return 0
    if args.lan:
        parsed = urlparse(args.base_url)
        try:
            address = ipaddress.IPv4Address(parsed.hostname)
            private = any(address in ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))
        except ValueError:
            private = False
        if parsed.scheme != 'http' or not private or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:
            raise SystemExit('LAN build requires a private IPv4 HTTP origin without credentials or path')
    elif not args.base_url.startswith("https://"):
        raise SystemExit("只接受 https:// 的地址：清单里关掉了明文流量，http 在手机上打不开。")
    built = [build(v, args.base_url, ks, pw, lan=args.lan) for v in VARIANTS if not args.only or v == args.only]
    print("\n成品：")
    served = HERE.parent / "backend" / "static" / "download"
    for p in built:
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        print(f"  {p}  {p.stat().st_size:,} B  sha256 {digest[:16]}…")
        if not args.no_copy:
            served.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, served / p.name)
            assert (served / p.name).read_bytes() == p.read_bytes()
            print(f"    → 已复制到 {served / p.name}（手机上打开 /download/{p.name} 下载）")
    if not args.no_copy:
        # 构建记录：拿哪一版源码编的、编出来的包是哪两个。判据拿它查「源码改了没重编」。
        record = {
            "version_name": VERSION_NAME,
            "version_code": VERSION_CODE,
            "base_url": args.base_url.rstrip("/"),
            "source_sha256": source_digest(),
            "lan_test": args.lan,
            "apks": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in built},
        }
        (served / ("app-build-info.json" if args.only == 'app' else "build-info.json")).write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"    → 构建记录 {served / 'build-info.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
