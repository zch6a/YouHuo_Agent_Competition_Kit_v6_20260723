"""Small Chinese recognizer for browser recordings; audio stays on our backend."""
from pathlib import Path
import importlib.util, json, os, tempfile, threading, time, urllib.request, tarfile, hashlib
from .asr import NeuralEars, REQUIRED_RATE

MODEL_URL='https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-paraformer-zh-small-2024-03-09.tar.bz2'
MODEL_NAME='sherpa-onnx-paraformer-zh-small-2024-03-09'
MODEL_SHA256='da92b3db5218c5be53aad53e57d1b6e63e7fc98a0e054fbdd6dbe18e9c6b1450'

class WebEars:
    def __init__(self):
        self.directory=Path(os.getenv('YOUHUO_WEB_ASR_DIR',str(Path(tempfile.gettempdir())/'youhuo-web-asr')))
        self.model=None
        self.error=None
        self.warming=False
        self.retry_at=0
        self.lock=threading.Lock()
        self.decode_lock=threading.Lock()

    def warm(self):
        with self.lock:
            if self.model is not None or self.warming or time.monotonic()<self.retry_at:return
            if importlib.util.find_spec('sherpa_onnx') is None:
                self.error='语音识别组件尚未安装。';return
            self.error=None
            self.warming=True
        threading.Thread(target=self._load,daemon=True,name='web-asr-load').start()

    def _load(self):
        try:
            target=self.directory/MODEL_NAME
            if not ((target/'model.int8.onnx').is_file() and (target/'tokens.txt').is_file()):
                self.directory.mkdir(parents=True,exist_ok=True)
                archive=self.directory/'model.download.tar.bz2'
                with urllib.request.urlopen(MODEL_URL,timeout=60) as response,archive.open('wb') as dest:
                    total=0
                    while chunk:=response.read(1024*1024):
                        total+=len(chunk)
                        if total>120*1024*1024:raise RuntimeError('模型下载超出大小限制')
                        dest.write(chunk)
                if hashlib.sha256(archive.read_bytes()).hexdigest()!=MODEL_SHA256:
                    raise RuntimeError('模型校验失败')
                with tarfile.open(archive) as package:
                    members=package.getmembers()
                    if sum(member.size for member in members)>180*1024*1024:raise RuntimeError('模型包超出大小限制')
                    for member in members:
                        if not (self.directory/member.name).resolve().is_relative_to(self.directory.resolve()):raise RuntimeError('模型包路径无效')
                        if not (member.isfile() or member.isdir()):raise RuntimeError('模型包文件无效')
                    package.extractall(self.directory,filter='data')
                archive.unlink(missing_ok=True)
            import sherpa_onnx
            self.model=sherpa_onnx.OfflineRecognizer.from_paraformer(
                paraformer=str(target/'model.int8.onnx'),tokens=str(target/'tokens.txt'),num_threads=1)
        except Exception as exc:
            self.error='语音识别服务暂未就绪，请稍后再试。'
            self.retry_at=time.monotonic()+60
            import logging
            logging.getLogger(__name__).warning('Web ASR load failed: %s',type(exc).__name__)
        finally:self.warming=False

    def status(self):
        self.warm()
        return {'available':self.model is not None,'warming':self.warming,'rate':REQUIRED_RATE,'max_seconds':20,'note':self.error or ('首次使用正在准备中文识别，请稍候。' if self.warming else None)}

    def transcribe(self,blob):
        if self.model is None:raise RuntimeError('语音识别正在准备，请稍后再试。')
        samples,rate=NeuralEars.decode(blob)
        if len(samples)>rate*20:raise ValueError('一次最多说20秒。')
        # Bound parallel decoding on the small public instance. Nothing is queued indefinitely.
        if not self.decode_lock.acquire(blocking=False):raise RuntimeError('小优正在听另一段话，请稍后再试。')
        try:
            import numpy as np
            audio=np.array(samples,dtype=np.float32)/32768.0
            if not len(audio) or float(np.sqrt(np.mean(audio*audio)))<0.002:
                text=''
            else:
                stream=self.model.create_stream()
                stream.accept_waveform(rate,audio)
                self.model.decode_stream(stream)
                text=stream.result.text.strip()
            return {'text':text,'heard':bool(text),'seconds':round(len(samples)/rate,2),'kind':'paraformer-zh'}
        finally:self.decode_lock.release()
