package com.youhuo.app;

import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.SystemClock;
import android.util.Base64;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Bounded, in-memory PCM capture, independent of WebView and speech services. */
final class PcmRecorder {
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private volatile Job current;
    private static final class Job {
        final String id;
        volatile boolean stop, cancel;
        volatile String state = "preparing", error = "";
        volatile int rate = 16000;
        volatile byte[] pcm;
        Job(String id) { this.id = id; }
    }
    synchronized void start(String id) {
        cancelAll();
        final Job job = new Job(id);
        current = job;
        worker.execute(new Runnable() { @Override public void run() { capture(job); } });
    }
    synchronized void stop(String id, boolean discard) {
        Job j = current;
        if (j != null && j.id.equals(id)) {
            j.cancel |= discard;
            j.stop = true;
            if (discard) { j.pcm = null; j.state = "cancelled"; }
        }
    }
    synchronized void cancelAll() {
        Job j = current;
        if (j != null) { j.cancel = true; j.stop = true; j.pcm = null; j.state = "cancelled"; }
    }
    synchronized String poll(String id) {
        try {
            JSONObject result = new JSONObject();
            Job j = current;
            if (j == null || !j.id.equals(id)) return result.put("state", "cancelled").toString();
            result.put("state", j.state).put("rate", j.rate).put("error", j.error);
            if ("done".equals(j.state) && j.pcm != null) {
                result.put("pcm", Base64.encodeToString(j.pcm, Base64.NO_WRAP));
                j.pcm = null; // Consume once; no audio is written to disk.
                j.state = "consumed";
            }
            return result.toString();
        } catch (Exception e) { return "{\"state\":\"error\",\"error\":\"NATIVE_RESULT\"}"; }
    }
    private void capture(Job j) {
        AudioRecord audio = null;
        try {
            // Voice recognition mode avoids communication-device routing; plain
            // microphone and a second sample rate cover device-driver differences.
            outer: for (int source : new int[]{MediaRecorder.AudioSource.VOICE_RECOGNITION, MediaRecorder.AudioSource.MIC}) {
                for (int rate : new int[]{16000, 48000}) {
                    if (j.stop) return;
                    int minimum = AudioRecord.getMinBufferSize(rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
                    if (minimum <= 0) continue;
                    try {
                        audio = new AudioRecord(source, rate, AudioFormat.CHANNEL_IN_MONO,
                            AudioFormat.ENCODING_PCM_16BIT, Math.max(minimum * 2, rate / 5 * 2));
                        if (audio.getState() == AudioRecord.STATE_INITIALIZED) {
                            audio.startRecording();
                            if (audio.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) {
                                j.rate = rate;
                                break outer;
                            }
                        }
                    } catch (SecurityException denied) { throw denied; }
                    catch (RuntimeException unsupported) { /* try next hardware configuration */ }
                    if (audio != null) { audio.release(); audio = null; }
                }
            }
            if (audio == null || audio.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING)
                throw new IllegalStateException("NATIVE_START");
            if (j.stop) return;
            j.state = "recording";
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            short[] buffer = new short[1024];
            long deadline = SystemClock.elapsedRealtime() + 20000;
            while (!j.stop && bytes.size() < j.rate * 2 * 19 && SystemClock.elapsedRealtime() < deadline) {
                int n = audio.read(buffer, 0, buffer.length, AudioRecord.READ_NON_BLOCKING);
                if (n < 0) throw new IllegalStateException("NATIVE_READ_" + n);
                if (n == 0) { SystemClock.sleep(10); continue; }
                for (int i = 0; i < n && bytes.size() < j.rate * 2 * 19; i++) {
                    bytes.write(buffer[i] & 255); bytes.write((buffer[i] >> 8) & 255);
                }
            }
            synchronized (this) {
                if (!j.cancel && current == j) j.pcm = bytes.toByteArray();
            }
        } catch (SecurityException denied) { j.error = "NATIVE_PERMISSION"; }
        catch (Exception e) { j.error = e.getMessage() != null && e.getMessage().startsWith("NATIVE_") ? e.getMessage() : "NATIVE_START"; }
        finally {
            if (audio != null) {
                try { if (audio.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) audio.stop(); } catch (Exception ignored) {}
                audio.release();
            }
            synchronized (this) {
                j.state = j.cancel ? "cancelled" : !j.error.isEmpty() ? "error" : "done";
            }
        }
    }
    void shutdown() { cancelAll(); worker.shutdown(); }
}
