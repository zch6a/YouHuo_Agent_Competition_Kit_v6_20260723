package com.youhuo.app;

import android.Manifest;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.GeolocationPermissions;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * 优活的手机外壳：一个全屏的网页视图，装着公网上那两页（老人端 /elder2、家人端 /family2）。
 *
 * 设计原则是「页面一个字不改，外壳补上浏览器在 App 里缺的那几样」：
 *   - 朗读与听写：安卓的网页视图没有 Web Speech，由 {@link NativeBridge} 用系统的
 *     朗读引擎和语音识别顶上（页面那一侧的垫片是 static/app-bridge.js）。
 *   - 「存一份」：网页视图不接 a[download] 的下载，由外壳写进手机的「下载」。
 *   - 打电话、外链：交给系统拨号盘和浏览器，不在壳里打开别人的网站。
 *   - 断网：一整屏说清楚「连不上」和「重试」，不留一张白纸。
 *   - 返回键：先退网页里的上一步，到头了把 App 放到后台（像普通 App 一样，不杀掉）。
 *
 * 哪一端由资源里的 start_url 决定；同一份代码编出两个 App（见 android/build_apk.py）。
 */
public class MainActivity extends Activity {

    static final int REQ_MIC = 7;
    static final int REQ_NOTIFY = 8;

    private WebView web;
    private View offline;
    private NativeBridge bridge;
    private String startUrl;
    private String host;
    private boolean mainFrameFailed;
    private PermissionRequest pendingWebPermission;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        startUrl = getString(R.string.start_url);
        host = Uri.parse(startUrl).getHost();
        paintSystemBars();

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(getColor(R.color.paper_bg));
        web = new WebView(this);
        // 和页面底色一样：第一次加载那一两秒不闪白。
        web.setBackgroundColor(getColor(R.color.paper_bg));
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        offline = buildOfflineView();
        offline.setVisibility(View.GONE);
        root.addView(offline, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);

        configureWebView();
        // Refresh HTTP assets on upgrade without deleting cookies or account data.
        String assetVersion = getSharedPreferences("app_session", MODE_PRIVATE).getString("asset_version", "");
        if (!BuildInfo.VERSION_NAME.equals(assetVersion)) {
            web.clearCache(true);
            getSharedPreferences("app_session", MODE_PRIVATE).edit().putString("asset_version", BuildInfo.VERSION_NAME).apply();
        }
        bridge = new NativeBridge(this, web);
        web.addJavascriptInterface(bridge, "YouhuoNative");

        if (savedInstanceState != null) {
            web.restoreState(savedInstanceState);
        }
        if (web.getUrl() == null) {
            web.loadUrl(startUrl);
        }
        ReminderPoller.start(this);
    }

    private void paintSystemBars() {
        Window w = getWindow();
        int bg = getColor(R.color.paper_bg);
        w.setStatusBarColor(bg);
        w.setNavigationBarColor(bg);
        int flags = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
        if (Build.VERSION.SDK_INT >= 26) {
            flags |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
        }
        w.getDecorView().setSystemUiVisibility(flags);
    }

    private void configureWebView() {
        // 只有调试版（build_apk.py --debug-local）能从电脑上连进网页视图看控制台；
        // 正式版不可调试，这一行不生效。
        if ((getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            WebView.setWebContentsDebuggingEnabled(true);
        }
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        // 回答是点完之后隔一两秒才回来的，要能直接出声。
        s.setMediaPlaybackRequiresUserGesture(false);
        // 页面自己有「字号」设置（1.0–1.8 倍），系统字号再叠一层会把版面撑破。
        s.setTextZoom(100);
        s.setSupportZoom(false);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setUserAgentString(s.getUserAgentString() + " YouHuoApp/" + BuildInfo.VERSION_NAME
                + " (" + getString(R.string.role) + ")");
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return route(request.getUrl());
            }

            @Override
            public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                mainFrameFailed = false;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (!mainFrameFailed) {
                    showOffline(false);
                }
                if (sameOrigin(Uri.parse(url))) {
                    // An old service worker may serve old recording JS even after
                    // installing a new APK. Clear only our disposable shell caches.
                    web.evaluateJavascript("(function(){try{var v='" + BuildInfo.VERSION_NAME
                        + "',k='youhuoNativeAssetVersion';if(localStorage.getItem(k)===v)return;"
                        + "localStorage.setItem(k,v);if(!window.caches)return;"
                        + "caches.keys().then(function(keys){return Promise.all(keys.filter(function(k){"
                        + "return k.indexOf('youhuo-shell-')===0;}).map(function(k){return caches.delete(k);}));})"
                        + ".then(function(){location.reload();}).catch(function(){});}catch(e){}})()", null);
                    String path = Uri.parse(url).getPath();
                    if ("/family4".equals(path) || "/elder4".equals(path)) {
                        getSharedPreferences("app_session", MODE_PRIVATE).edit()
                            .putString("role", "/family4".equals(path) ? "family" : "elder").apply();
                    }
                }
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    mainFrameFailed = true;
                    showOffline(true);
                }
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request,
                                            WebResourceResponse response) {
                // 服务器在冷启动或挂了（502/503/504）：比一页英文报错更该给她一个「重试」。
                if (request.isForMainFrame() && response.getStatusCode() >= 500) {
                    mainFrameFailed = true;
                    showOffline(true);
                }
            }
        });

        // 普通的文件下载（不是页面自己拼出来的 blob:，那种由 app-bridge.js 接手）：
        // 网页视图默认什么都不做，点了没反应。交给系统（浏览器 / 下载管理器）。
        web.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent, String contentDisposition,
                                        String mimetype, long contentLength) {
                if (url == null || url.startsWith("blob:") || url.startsWith("data:")) return;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))
                            .addCategory(Intent.CATEGORY_BROWSABLE));
                } catch (ActivityNotFoundException ignored) {
                    // 没有能接的 App：不崩
                }
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(final PermissionRequest request) {
                // 只给自己那个站点的麦克风；别的一概不给。
                boolean ours = sameOrigin(request.getOrigin());
                boolean wantsMic = false;
                for (String r : request.getResources()) {
                    if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(r)) wantsMic = true;
                }
                if (!ours || !wantsMic) {
                    request.deny();
                    return;
                }
                if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                    request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
                } else {
                    pendingWebPermission = request;
                    requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_MIC);
                }
            }

            @Override
            public void onPermissionRequestCanceled(PermissionRequest request) {
                if (pendingWebPermission == request) pendingWebPermission = null;
            }

            @Override
            public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
                // 这两页不用定位；不申请、不给。
                callback.invoke(origin, false, false);
            }
        });
    }

    /** 这个链接在壳里开，还是交给系统。返回 true 表示壳不管了。 */
    boolean route(Uri uri) {
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase();
        if (("https".equals(scheme) || "http".equals(scheme)) && sameOrigin(uri)) {
            return false;
        }
        Intent intent;
        if ("tel".equals(scheme)) {
            intent = new Intent(Intent.ACTION_DIAL, uri);      // 只拨出号码，不替她按下拨打
        } else if ("mailto".equals(scheme) || "sms".equals(scheme) || "smsto".equals(scheme)) {
            intent = new Intent(Intent.ACTION_SENDTO, uri);
        } else {
            intent = new Intent(Intent.ACTION_VIEW, uri);
            intent.addCategory(Intent.CATEGORY_BROWSABLE);
        }
        try {
            startActivity(intent);
        } catch (ActivityNotFoundException ignored) {
            // 手机上没有能打开它的 App：什么也不做，比崩掉强。
        }
        return true;
    }

    private boolean sameOrigin(Uri uri) {
        Uri trusted = Uri.parse(startUrl);
        int a = uri.getPort() == -1 ? ("https".equals(uri.getScheme()) ? 443 : 80) : uri.getPort();
        int b = trusted.getPort() == -1 ? ("https".equals(trusted.getScheme()) ? 443 : 80) : trusted.getPort();
        return trusted.getScheme().equals(uri.getScheme()) && host != null
            && host.equals(uri.getHost()) && a == b && uri.getUserInfo() == null;
    }

    private View buildOfflineView() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setBackgroundColor(getColor(R.color.paper_bg));
        int pad = dp(32);
        box.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText(R.string.offline_title);
        title.setTextColor(getColor(R.color.ink));
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 26);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setGravity(Gravity.CENTER);
        box.addView(title);

        TextView body = new TextView(this);
        body.setText(R.string.offline_body);
        body.setTextColor(getColor(R.color.ink_soft));
        body.setTextSize(TypedValue.COMPLEX_UNIT_SP, 19);
        body.setGravity(Gravity.CENTER);
        body.setLineSpacing(0, 1.25f);
        LinearLayout.LayoutParams bodyLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        bodyLp.topMargin = dp(16);
        bodyLp.bottomMargin = dp(32);
        box.addView(body, bodyLp);

        Button retry = new Button(this);
        retry.setText(R.string.offline_retry);
        retry.setTextColor(Color.WHITE);
        retry.setTextSize(TypedValue.COMPLEX_UNIT_SP, 21);
        retry.setAllCaps(false);
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(getColor(R.color.jade));
        shape.setCornerRadius(dp(16));
        retry.setBackground(shape);
        retry.setMinHeight(dp(60));
        retry.setMinimumHeight(dp(60));
        retry.setPadding(dp(40), 0, dp(40), 0);
        retry.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showOffline(false);
                if (web.getUrl() == null || mainFrameFailed) {
                    web.loadUrl(startUrl);
                } else {
                    web.reload();
                }
            }
        });
        box.addView(retry, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        return box;
    }

    void showOffline(boolean show) {
        offline.setVisibility(show ? View.VISIBLE : View.GONE);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    @Override
    public void onBackPressed() {
        if (offline.getVisibility() == View.VISIBLE) {
            moveTaskToBack(true);
            return;
        }
        if (web.canGoBack()) {
            web.goBack();
            return;
        }
        // 到头了：放到后台，下次点开还在原处（普通 App 的样子），不是退出重来。
        moveTaskToBack(true);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        boolean granted = results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED;
        if (requestCode == REQ_MIC) {
            if (pendingWebPermission != null) {
                if (granted) {
                    pendingWebPermission.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
                } else {
                    pendingWebPermission.deny();
                }
                pendingWebPermission = null;
            }
            bridge.onMicPermission(granted);
        } else if (requestCode == REQ_NOTIFY) {
            ReminderPoller.start(this);
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        web.saveState(outState);
    }

    @Override
    protected void onResume() {
        super.onResume();
        web.onResume();
        ReminderPoller.setForeground(true);
    }

    @Override
    protected void onPause() {
        if (bridge != null) bridge.cancelPcmRecording();
        ReminderPoller.setForeground(false);
        web.onPause();
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        bridge.shutdown();
        web.destroy();
        super.onDestroy();
    }
}
