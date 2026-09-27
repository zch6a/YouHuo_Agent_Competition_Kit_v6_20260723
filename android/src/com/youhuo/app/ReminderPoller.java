package com.youhuo.app;

import android.Manifest;
import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * 主动服务在手机上「看得见」的那一半：服务器定时器发出的提醒，变成系统通知。
 *
 * 页面开着的时候，小优会在屏幕上把新提醒念出来（elder-v6-b.js 的 checkReminders），
 * 这里就**不再**弹通知，免得一件事说两遍。App 退到后台以后：
 *   - 进程还在：每 60 秒问一次服务器的收件箱（和页面问的是同一个接口）；
 *   - 进程被系统收掉：JobScheduler 每 15 分钟叫醒一次（安卓允许的最短周期）。
 * 第一次只记下当前最大的编号，旧的不弹——和页面那边「第一次只记起点」是同一个规矩。
 */
final class ReminderPoller {

    static final String CHANNEL = "reminders";
    private static final int JOB_ID = 20260924;
    private static final long FOREGROUND_POLL_MS = 60_000L;
    private static final String PREFS = "reminders";
    private static final String KEY_LAST_ID = "last_id";

    private static final Handler main = new Handler(Looper.getMainLooper());
    private static volatile boolean foreground;
    private static volatile boolean loopRunning;
    private static Context appContext;

    private ReminderPoller() { }

    /** 建通知频道、要通知权限（安卓 13 起）、排上后台任务、起前台轮询。可以重复调用。 */
    static void start(Activity activity) {
        appContext = activity.getApplicationContext();
        createChannel(appContext);
        if (Build.VERSION.SDK_INT >= 33
                && activity.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            SharedPreferences prefs = prefs(appContext);
            // 只主动问一次；她拒绝了就不再追着问（系统设置里随时能开）。
            if (!prefs.getBoolean("asked_notify", false)) {
                prefs.edit().putBoolean("asked_notify", true).apply();
                activity.requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},
                        MainActivity.REQ_NOTIFY);
            }
        }
        scheduleJob(appContext);
        if (!loopRunning) {
            loopRunning = true;
            main.postDelayed(loop, FOREGROUND_POLL_MS);
        }
    }

    static void setForeground(boolean value) {
        foreground = value;
    }

    static boolean isForeground() {
        return foreground;
    }

    private static final Runnable loop = new Runnable() {
        @Override
        public void run() {
            final Context ctx = appContext;
            if (ctx != null) {
                new Thread(new Runnable() {
                    @Override
                    public void run() {
                        pollOnce(ctx, !foreground);
                    }
                }, "youhuo-reminders").start();
            }
            main.postDelayed(this, FOREGROUND_POLL_MS);
        }
    };

    private static void scheduleJob(Context ctx) {
        JobScheduler js = (JobScheduler) ctx.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (js == null) return;
        for (JobInfo existing : js.getAllPendingJobs()) {
            if (existing.getId() == JOB_ID) return;
        }
        JobInfo job = new JobInfo.Builder(JOB_ID, new ComponentName(ctx, ReminderJob.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPeriodic(15 * 60 * 1000L)
                .setPersisted(false)
                .build();
        js.schedule(job);
    }

    private static void createChannel(Context ctx) {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager nm = ctx.getSystemService(NotificationManager.class);
        if (nm == null || nm.getNotificationChannel(CHANNEL) != null) return;
        NotificationChannel ch = new NotificationChannel(CHANNEL,
                ctx.getString(R.string.channel_name), NotificationManager.IMPORTANCE_HIGH);
        ch.setDescription(ctx.getString(R.string.channel_desc));
        nm.createNotificationChannel(ch);
    }

    private static SharedPreferences prefs(Context ctx) {
        return ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    /**
     * 问一次收件箱。`notify` 为 false 时只推进编号（前台：页面自己会说）。
     * 任何失败都安静地算了——下一轮再问，不打扰她。
     */
    static void pollOnce(Context ctx, boolean notify) {
        HttpURLConnection conn = null;
        try {
            Uri start = Uri.parse(ctx.getString(R.string.start_url));
            SharedPreferences session = ctx.getSharedPreferences("app_session", Context.MODE_PRIVATE);
            String role = session.getString("role", ctx.getString(R.string.role));
            String token = session.getString("token_" + role, "");
            if (token.isEmpty()) return;
            String cursor = KEY_LAST_ID + "_" + role + "_" + token.hashCode();
            String path = "family".equals(role)
                    ? "/api/v1/notifications?role=family" : "/api/v1/notifications";
            URL url = new URL(start.getScheme() + "://" + start.getAuthority() + path);
            conn = (HttpURLConnection) url.openConnection();
            conn.setConnectTimeout(10_000);
            conn.setReadTimeout(15_000);
            conn.setRequestProperty("Accept", "application/json");
            conn.setRequestProperty("Authorization", "Bearer " + token);
            if (conn.getResponseCode() != 200) return;
            InputStream in = conn.getInputStream();
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            byte[] chunk = new byte[8192];
            int n;
            while ((n = in.read(chunk)) > 0) buf.write(chunk, 0, n);
            in.close();
            JSONArray items = new JSONObject(new String(buf.toByteArray(), StandardCharsets.UTF_8))
                    .optJSONArray("items");
            if (items == null) return;

            long maxId = 0;
            for (int i = 0; i < items.length(); i++) {
                maxId = Math.max(maxId, items.getJSONObject(i).optLong("id", 0));
            }
            SharedPreferences p = prefs(ctx);
            long lastId = p.getLong(cursor, -1);
            if (lastId < 0) {                      // 第一次：只记起点
                p.edit().putLong(cursor, maxId).apply();
                return;
            }
            JSONObject newest = null;
            int fresh = 0;
            for (int i = 0; i < items.length(); i++) {
                JSONObject it = items.getJSONObject(i);
                long id = it.optLong("id", 0);
                if (id > lastId && !it.optBoolean("read", false)) {
                    fresh++;
                    if (newest == null || id > newest.optLong("id", 0)) newest = it;
                }
            }
            if (maxId > lastId) {
                p.edit().putLong(cursor, maxId).apply();
            }
            if (notify && newest != null && role.equals(session.getString("role", ""))
                    && token.equals(session.getString("token_" + role, ""))) {
                String title = newest.optString("title", "").trim();
                if (!title.isEmpty()) {
                    post(ctx, (int) (newest.optLong("id", 0) % Integer.MAX_VALUE), title, fresh);
                }
            }
        } catch (Exception ignored) {
            // 断网、服务器冷启动、格式变了：这一轮算了
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private static void post(Context ctx, int id, String title, int count) {
        if (Build.VERSION.SDK_INT >= 33
                && ctx.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            return;
        }
        NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) return;
        Intent open = new Intent(ctx, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent tap = PendingIntent.getActivity(ctx, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        String text = count > 1 ? ctx.getString(R.string.notify_more, title, count - 1) : title;
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(ctx, CHANNEL) : new Notification.Builder(ctx);
        b.setSmallIcon(R.drawable.ic_notify)
                .setContentTitle(ctx.getString(R.string.app_name))
                .setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(text))
                .setContentIntent(tap)
                .setAutoCancel(true)
                .setCategory(Notification.CATEGORY_REMINDER)
                .setColor(ctx.getColor(R.color.jade));
        if (Build.VERSION.SDK_INT < 26) {
            b.setPriority(Notification.PRIORITY_HIGH).setDefaults(Notification.DEFAULT_ALL);
        }
        nm.notify(id, b.build());
    }
}
