package com.sanford.gtinscanner.app

import android.app.Application
import com.sanford.gtinscanner.core.ScanController

class GtinScannerApp : Application() {
    val database: Database by lazy { Database(this) }

    val scanController: ScanController by lazy {
        ScanController(database.opQueue, database.reference, database.sessionLog)
    }

    override fun onCreate() {
        super.onCreate()
        SyncScheduler.schedulePeriodic(this)
    }
}
