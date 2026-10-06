plugins {
    id("com.android.application")
    kotlin("android")
}

android {
    namespace = "com.sanford.gtinscanner.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.sanford.gtinscanner"
        // The Zebra HC50 runs Android 11+; 26 also gives java.time without desugaring.
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    implementation(project(":core"))
    implementation("androidx.work:work-runtime:2.9.1")
}
