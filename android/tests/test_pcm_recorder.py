"""Exercise recorder lifecycle with a deterministic fake Android audio driver.
This tests ownership and cleanup, not microphone compatibility on real devices.
"""
from pathlib import Path
import os, shutil, subprocess, tempfile

JDK = Path(os.environ.get('JAVA_HOME', 'D:/DevEco/jdk17/jdk-17.0.20.1+1')) / 'bin'
STUBS = {
'android/media/AudioFormat.java': '''package android.media; public class AudioFormat { public static final int CHANNEL_IN_MONO=16,ENCODING_PCM_16BIT=2; }''',
'android/media/MediaRecorder.java': '''package android.media; public class MediaRecorder { public static class AudioSource {public static final int MIC=1,VOICE_RECOGNITION=6;} }''',
'android/os/SystemClock.java': '''package android.os; public class SystemClock { public static long elapsedRealtime(){return System.nanoTime()/1000000;} public static void sleep(long n){try{Thread.sleep(n);}catch(Exception e){}} }''',
'android/util/Base64.java': '''package android.util; public class Base64 {public static final int NO_WRAP=2; public static String encodeToString(byte[] b,int f){return java.util.Base64.getEncoder().encodeToString(b);} }''',
'org/json/JSONObject.java': '''package org.json; public class JSONObject {private final java.util.Map<String,Object> data=new java.util.LinkedHashMap<>(); public JSONObject put(String k,Object v){data.put(k,v);return this;} public String toString(){return data.toString();}}''',
'android/media/AudioRecord.java': '''package android.media;
public class AudioRecord {
 public static final int STATE_INITIALIZED=1,RECORDSTATE_RECORDING=3,READ_NON_BLOCKING=1;
 public static volatile int live=0,maxLive=0,mode=0; private boolean recording=false,released=false; private final boolean supported;
 public static int getMinBufferSize(int r,int c,int e){return 1024;}
 public AudioRecord(int source,int rate,int c,int e,int size){
  if(mode==3)throw new SecurityException();
  synchronized(AudioRecord.class){live++;maxLive=Math.max(maxLive,live);}
  supported=mode==0 || (mode==1 && source==1 && rate==48000);
 }
 public int getState(){return supported?1:0;}
 public void startRecording(){recording=true;}
 public int getRecordingState(){return recording?3:1;}
 public int read(short[] b,int o,int n,int m){android.os.SystemClock.sleep(2);java.util.Arrays.fill(b,(short)100);return n;}
 public void stop(){recording=false;}
 public void release(){synchronized(AudioRecord.class){if(released)throw new AssertionError("double release");released=true;live--;}}
}''',
'com/youhuo/app/PcmRecorderTest.java': '''package com.youhuo.app;
import android.media.AudioRecord;
public class PcmRecorderTest {
 static void check(boolean b,String message){if(!b)throw new AssertionError(message);}
 static String waitFor(PcmRecorder r,String id,String state)throws Exception{for(int i=0;i<500;i++){String s=r.poll(id);if(s.contains("state="+state))return s;Thread.sleep(2);}throw new AssertionError("timeout "+state);}
 static void released()throws Exception{for(int i=0;i<500&&AudioRecord.live!=0;i++)Thread.sleep(2);check(AudioRecord.live==0,"device leak");}
 public static void main(String[] args)throws Exception{
  PcmRecorder r=new PcmRecorder();
  try{
   r.start("one");waitFor(r,"one","recording");Thread.sleep(15);r.stop("one",false);
   String done=waitFor(r,"one","done");check(done.contains("pcm=")&&done.contains("rate=16000"),"no PCM");check(r.poll("one").contains("consumed"),"consume once");released();
   r.start("old");waitFor(r,"old","recording");r.start("new");waitFor(r,"new","recording");check(r.poll("old").contains("cancelled"),"stale result");r.cancelAll();released();check(AudioRecord.maxLive==1,"overlapping devices");
   AudioRecord.mode=1;r.start("fallback");String fallback=waitFor(r,"fallback","recording");check(fallback.contains("rate=48000"),"rate/source fallback failed");r.cancelAll();released();
   AudioRecord.mode=2;r.start("bad");check(waitFor(r,"bad","error").contains("NATIVE_START"),"startup diagnostic");released();
   AudioRecord.mode=3;r.start("denied");check(waitFor(r,"denied","error").contains("NATIVE_PERMISSION"),"permission diagnostic");released();
   System.out.println("PASS native release, consume once, rapid restart, fallback, failure and permission");
  }finally{r.shutdown();}
 }
}'''
}

def test_native_recorder_lifecycle():
    with tempfile.TemporaryDirectory(prefix='youhuo-pcm-test-') as tmp:
        root=Path(tmp)
        for name,content in STUBS.items():
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content,encoding='utf-8')
        shutil.copyfile(Path(__file__).resolve().parents[1]/'src/com/youhuo/app/PcmRecorder.java',root/'com/youhuo/app/PcmRecorder.java')
        subprocess.run([str(JDK/'javac.exe'),'-encoding','UTF-8','-d',str(root),*[str(p) for p in root.rglob('*.java')]],check=True,timeout=30)
        subprocess.run([str(JDK/'java.exe'),'-cp',str(root),'com.youhuo.app.PcmRecorderTest'],check=True,timeout=20)

if __name__=='__main__': test_native_recorder_lifecycle()
