package com.youhuo.app;

import android.app.job.JobParameters;
import android.app.job.JobService;

/** App 被系统收掉以后，每 15 分钟被叫醒一次，问一遍收件箱（见 {@link ReminderPoller}）。 */
public class ReminderJob extends JobService {

    @Override
    public boolean onStartJob(final JobParameters params) {
        new Thread(new Runnable() {
            @Override
            public void run() {
                // 页面正开着的时候由小优在屏幕上说，这里只推进编号。
                ReminderPoller.pollOnce(getApplicationContext(), !ReminderPoller.isForeground());
                jobFinished(params, false);
            }
        }, "youhuo-reminder-job").start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return false;
    }
}
