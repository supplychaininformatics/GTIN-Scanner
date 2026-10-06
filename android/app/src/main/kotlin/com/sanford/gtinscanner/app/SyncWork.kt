package com.sanford.gtinscanner.app

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import com.sanford.gtinscanner.core.HttpUrlConnectionTransport
import com.sanford.gtinscanner.core.MirrorResult
import com.sanford.gtinscanner.core.MirrorUpdater
import com.sanford.gtinscanner.core.SyncEngine
import com.sanford.gtinscanner.core.SyncStatus
import java.util.concurrent.TimeUnit

/** Uploads queued operations, then refreshes the contract-line mirror. */
class SyncWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val app = applicationContext as GtinScannerApp
        val config = ConfigSource.load(applicationContext) ?: return Result.failure() // not provisioned yet
        val transport = HttpUrlConnectionTransport(config.syncUrl, config.token, config.allowCleartext)

        // Upload first: the queue matters more than the mirror.
        val sync = SyncEngine(transport, app.database.opQueue).syncOnce()
        val mirror = MirrorUpdater(transport, app.database.reference).update()

        return when {
            // A refused token or a request the server calls malformed will not
            // fix itself by retrying; surface it instead of looping.
            sync.status == SyncStatus.AUTH_FAILED || mirror is MirrorResult.AuthFailed -> Result.failure()
            sync.status == SyncStatus.PROTOCOL_ERROR -> Result.failure()
            sync.status == SyncStatus.DRAINED &&
                (mirror is MirrorResult.UpToDate || mirror is MirrorResult.Updated) -> Result.success()
            else -> Result.retry() // offline, rate-limited, server error, or ops told to retry
        }
    }
}

object SyncScheduler {
    private const val NOW = "sync-now"
    private const val PERIODIC = "sync-periodic"

    private val needsNetwork = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

    /** Run a sync as soon as the network allows. Safe to call after every scan. */
    fun kick(context: Context) {
        val request = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(needsNetwork)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        // APPEND_OR_REPLACE, not KEEP: a scan made while a sync is mid-flight
        // must still get its own run afterwards.
        WorkManager.getInstance(context)
            .enqueueUniqueWork(NOW, ExistingWorkPolicy.APPEND_OR_REPLACE, request)
    }

    /** Safety net: also sync (and refresh the mirror) periodically. */
    fun schedulePeriodic(context: Context) {
        val request = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
            .setConstraints(needsNetwork)
            .build()
        WorkManager.getInstance(context)
            .enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.KEEP, request)
    }
}
