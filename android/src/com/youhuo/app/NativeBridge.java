package com.youhuo.app;

import android.Manifest;
import android.app.Activity;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Locale;

/**
 * 页面里 `window.YouhuoNative` 背后的东西。页面那一侧的垫片是 static/app-bridge.js：
 * 它把这几个方法包成 `speechSynthesis` / `webkitSpeechRecognition` 的样子，
 * 于是页面一个字不改，在 App 里照样能念、能听。
 *
 * 所有回调都经 `window.__youhuoBridge.*` 回到页面，且只在主线程上调 evaluateJavascript。
 * `@JavascriptInterface` 方法跑在网页视图自己的线程上，所以一律先 post 到主线程再动。
 */
final class NativeBridge implements TextToSpeech.OnInitListener {

    private final Activity activity;
    private final WebView web;
    private final Handler main = new Handler(Looper.getMainLooper());

    // ---- 朗读：系统自带的引擎（页面那条好听的服务器声音不可用时的兜底）
    private TextToSpeech tts;
    /** 0 还在初始化；1 能用；-1 这台手机上没有可用的朗读引擎。 */
    private volatile int ttsState = 0;
    private final ArrayList<String[]> queued = new ArrayList<>();

    // ---- 听写：系统的语音识别
    private SpeechRecognizer recognizer;
    private String listeningId;
    private String pendingListenId;
    private String pendingListenLang;

    NativeBridge(Activity activity, WebView web) {
        this.activity = activity;
        this.web = web;
        this.tts = new TextToSpeech(activity.getApplicationContext(), this);
    }

    // ================================================================ 页面问：这是哪个 App
    @JavascriptInterface
    public String appInfo() {
        try {
            JSONObject o = new JSONObject();
            o.put("version", BuildInfo.VERSION_NAME);
            o.put("role", activity.getSharedPreferences("app_session", Activity.MODE_PRIVATE)
                .getString("role", activity.getString(R.string.role)));
            o.put("platform", "android");
            o.put("sdk", Build.VERSION.SDK_INT);
            return o.toString();
        } catch (Exception e) {
            return "{}";
        }
    }

    @JavascriptInterface
    public void syncSession(String role, String token) {
        if (!("elder".equals(role) || "family".equals(role)) || token == null
                || !token.matches("[A-Za-z0-9_.-]{20,8192}")) return;
        activity.getSharedPreferences("app_session", Activity.MODE_PRIVATE).edit()
            .putString("role", role).putString("token_" + role, token).apply();
    }

    // ================================================================ 朗读
    @Override
    public void onInit(final int status) {
        main.post(new Runnable() {
            @Override
            public void run() {
                if (status == TextToSpeech.SUCCESS && tts != null) {
                    tts.setLanguage(Locale.SIMPLIFIED_CHINESE);
                    tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                        @Override
                        public void onStart(String id) { ttsEvent(id, "start"); }

                        @Override
                        public void onDone(String id) { ttsEvent(id, "end"); }

                        @Override
                        public void onError(String id) { ttsEvent(id, "error"); }

                        @Override
                        public void onError(String id, int code) { ttsEvent(id, "error"); }
                    });
                    ttsState = 1;
                    for (String[] item : queued) {
                        speakNow(item[0], item[1], Float.parseFloat(item[2]), Float.parseFloat(item[3]));
                    }
                } else {
                    ttsState = -1;
                    for (String[] item : queued) {
                        ttsEvent(item[0], "error");
                    }
                }
                queued.clear();
                js("window.__youhuoBridge&&window.__youhuoBridge.ttsReady(" + (ttsState == 1) + ")");
            }
        });
    }

    @JavascriptInterface
    public boolean ttsAvailable() {
        return ttsState != -1;
    }

    @JavascriptInterface
    public void speak(final String id, final String text, final float rate, final float pitch) {
        main.post(new Runnable() {
            @Override
            public void run() {
                if (ttsState == -1) {
                    ttsEvent(id, "error");
                } else if (ttsState == 0) {
                    queued.add(new String[]{id, text, String.valueOf(rate), String.valueOf(pitch)});
                } else {
                    speakNow(id, text, rate, pitch);
                }
            }
        });
    }

    private void speakNow(String id, String text, float rate, float pitch) {
        tts.setSpeechRate(clamp(rate, 0.3f, 2.5f));
        tts.setPitch(clamp(pitch, 0.5f, 2.0f));
        int r = tts.speak(text, TextToSpeech.QUEUE_ADD, new Bundle(), id);
        if (r != TextToSpeech.SUCCESS) {
            ttsEvent(id, "error");
        }
    }

    @JavascriptInterface
    public void stopSpeaking() {
        main.post(new Runnable() {
            @Override
            public void run() {
                queued.clear();
                if (ttsState == 1) {
                    tts.stop();
                }
            }
        });
    }

    private void ttsEvent(String id, String type) {
        js("window.__youhuoBridge&&window.__youhuoBridge.ttsEvent(" + JSONObject.quote(id) + ","
                + JSONObject.quote(type) + ")");
    }

    // ================================================================ 听写
    @JavascriptInterface
    public boolean asrAvailable() {
        return SpeechRecognizer.isRecognitionAvailable(activity);
    }

    @JavascriptInterface
    public void startListening(final String id, final String lang) {
        main.post(new Runnable() {
            @Override
            public void run() {
                if (activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                        != PackageManager.PERMISSION_GRANTED) {
                    pendingListenId = id;
                    pendingListenLang = lang;
                    activity.requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO},
                            MainActivity.REQ_MIC);
                    return;
                }
                beginListening(id, lang);
            }
        });
    }

    /** MainActivity 收到麦克风授权结果时转过来。 */
    void onMicPermission(boolean granted) {
        if (pendingListenId == null) {
            return;
        }
        String id = pendingListenId;
        String lang = pendingListenLang;
        pendingListenId = null;
        if (granted) {
            beginListening(id, lang);
        } else {
            asrEvent(id, "error", JSONObject.quote("not-allowed"));
            asrEvent(id, "end", "null");
        }
    }

    private void beginListening(String id, String lang) {
        if (!SpeechRecognizer.isRecognitionAvailable(activity)) {
            asrEvent(id, "error", JSONObject.quote("service-not-allowed"));
            asrEvent(id, "end", "null");
            return;
        }
        if (listeningId != null && recognizer != null) {
            // 上一轮还没收尾：先告诉页面它被打断了，再开这一轮。
            String previous = listeningId;
            listeningId = null;
            recognizer.cancel();
            asrEvent(previous, "error", JSONObject.quote("aborted"));
            asrEvent(previous, "end", "null");
        }
        if (recognizer == null) {
            recognizer = SpeechRecognizer.createSpeechRecognizer(activity);
            recognizer.setRecognitionListener(new Listener());
        }
        listeningId = id;
        Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, lang == null || lang.isEmpty() ? "zh-CN" : lang);
        intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3);
        intent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false);
        intent.putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, activity.getPackageName());
        recognizer.startListening(intent);
    }

    @JavascriptInterface
    public void stopListening() {
        main.post(new Runnable() {
            @Override
            public void run() {
                if (recognizer != null && listeningId != null) {
                    recognizer.stopListening();          // 说完了：把已经听到的交出来
                }
            }
        });
    }

    @JavascriptInterface
    public void abortListening() {
        main.post(new Runnable() {
            @Override
            public void run() {
                if (recognizer != null && listeningId != null) {
                    String id = listeningId;
                    listeningId = null;
                    recognizer.cancel();
                    asrEvent(id, "error", JSONObject.quote("aborted"));
                    asrEvent(id, "end", "null");
                }
            }
        });
    }

    private final class Listener implements RecognitionListener {
        @Override
        public void onReadyForSpeech(Bundle params) {
            if (listeningId != null) asrEvent(listeningId, "start", "null");
        }

        @Override
        public void onResults(Bundle results) {
            String id = listeningId;
            if (id == null) return;
            listeningId = null;
            ArrayList<String> texts = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
            float[] scores = results.getFloatArray(SpeechRecognizer.CONFIDENCE_SCORES);
            if (texts == null || texts.isEmpty()) {
                asrEvent(id, "error", JSONObject.quote("no-speech"));
            } else {
                JSONArray alts = new JSONArray();
                for (int i = 0; i < texts.size(); i++) {
                    try {
                        JSONObject alt = new JSONObject();
                        alt.put("transcript", texts.get(i));
                        alt.put("confidence", scores != null && i < scores.length ? scores[i] : 0.9);
                        alts.put(alt);
                    } catch (Exception ignored) {
                        // 一条候选坏了就跳过它
                    }
                }
                asrEvent(id, "result", alts.toString());
            }
            asrEvent(id, "end", "null");
        }

        @Override
        public void onError(int error) {
            String id = listeningId;
            if (id == null) return;
            listeningId = null;
            asrEvent(id, "error", JSONObject.quote(webErrorFor(error)));
            asrEvent(id, "end", "null");
        }

        @Override public void onBeginningOfSpeech() { }
        @Override public void onRmsChanged(float rmsdB) { }
        @Override public void onBufferReceived(byte[] buffer) { }
        @Override public void onEndOfSpeech() { }
        @Override public void onPartialResults(Bundle partialResults) { }
        @Override public void onEvent(int eventType, Bundle params) { }
    }

    /** 安卓的错误码换成网页那套（elder.js 按这几个词给她说人话）。 */
    static String webErrorFor(int error) {
        switch (error) {
            case SpeechRecognizer.ERROR_NO_MATCH:
            case SpeechRecognizer.ERROR_SPEECH_TIMEOUT:
                return "no-speech";
            case SpeechRecognizer.ERROR_AUDIO:
                return "audio-capture";
            case SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS:
                return "not-allowed";
            case SpeechRecognizer.ERROR_CLIENT:
                return "aborted";
            case SpeechRecognizer.ERROR_RECOGNIZER_BUSY:
                return "service-not-allowed";
            default:
                return "network";
        }
    }

    private void asrEvent(String id, String type, String payloadJson) {
        js("window.__youhuoBridge&&window.__youhuoBridge.asrEvent(" + JSONObject.quote(id) + ","
                + JSONObject.quote(type) + "," + payloadJson + ")");
    }

    // ================================================================ 存一份
    @JavascriptInterface
    public void saveText(final String filename, final String text) {
        main.post(new Runnable() {
            @Override
            public void run() {
                String safe = (filename == null || filename.trim().isEmpty() ? "优活.txt" : filename)
                        .replaceAll("[\\\\/:*?\"<>|]", "_");
                byte[] bytes = (text == null ? "" : text).getBytes(StandardCharsets.UTF_8);
                try {
                    if (Build.VERSION.SDK_INT >= 29) {
                        ContentResolver resolver = activity.getContentResolver();
                        ContentValues values = new ContentValues();
                        values.put(MediaStore.Downloads.DISPLAY_NAME, safe);
                        values.put(MediaStore.Downloads.MIME_TYPE, "text/plain");
                        values.put(MediaStore.Downloads.IS_PENDING, 1);
                        Uri uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
                        if (uri == null) throw new IllegalStateException("insert");
                        OutputStream out = resolver.openOutputStream(uri);
                        if (out == null) throw new IllegalStateException("open");
                        try {
                            out.write(bytes);
                        } finally {
                            out.close();
                        }
                        values.clear();
                        values.put(MediaStore.Downloads.IS_PENDING, 0);
                        resolver.update(uri, values, null, null);
                        toast(activity.getString(R.string.saved_to_downloads, safe));
                    } else {
                        File dir = activity.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
                        if (dir == null) throw new IllegalStateException("dir");
                        File file = new File(dir, safe);
                        FileOutputStream out = new FileOutputStream(file);
                        try {
                            out.write(bytes);
                        } finally {
                            out.close();
                        }
                        toast(activity.getString(R.string.saved_to_path, file.getAbsolutePath()));
                    }
                } catch (Exception e) {
                    toast(activity.getString(R.string.save_failed));
                }
            }
        });
    }

    // ================================================================ 杂项
    private void toast(String message) {
        Toast.makeText(activity, message, Toast.LENGTH_LONG).show();
    }

    private void js(final String script) {
        main.post(new Runnable() {
            @Override
            public void run() {
                web.evaluateJavascript(script, null);
            }
        });
    }

    private static float clamp(float v, float lo, float hi) {
        if (Float.isNaN(v)) return 1.0f;
        return Math.max(lo, Math.min(hi, v));
    }

    void shutdown() {
        if (recognizer != null) {
            recognizer.destroy();
            recognizer = null;
        }
        if (tts != null) {
            tts.shutdown();
            tts = null;
        }
    }
}
