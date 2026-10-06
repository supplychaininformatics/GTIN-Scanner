pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
    plugins {
        kotlin("jvm") version "2.0.21"
        kotlin("android") version "2.0.21"
        id("com.android.application") version "8.5.2"
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "gtin-scanner-android"

// :core is plain JVM Kotlin (protocol, queue, mirror logic) and builds anywhere
// with a JDK. :app is the Android layer and needs the Android SDK, so it is only
// included when one is configured — that keeps `gradle :core:test` working on a
// machine (or CI job) without the SDK.
include(":core")
val hasAndroidSdk = System.getenv("ANDROID_HOME") != null ||
    System.getenv("ANDROID_SDK_ROOT") != null ||
    file("local.properties").exists()
if (hasAndroidSdk) include(":app")
