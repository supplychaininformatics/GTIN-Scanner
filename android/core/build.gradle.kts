plugins {
    kotlin("jvm")
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    // Android ships org.json in the platform, so it is compileOnly here (an
    // extra copy in the APK causes duplicate-class problems) and a real
    // dependency only for the JVM unit tests.
    compileOnly("org.json:json:20240303")
    testImplementation("org.json:json:20240303")
    testImplementation(kotlin("test"))
}

tasks.test {
    useJUnitPlatform()
    // The live-server test reads these when set; see LiveServerTest.
    environment("SYNC_API_URL", System.getenv("SYNC_API_URL") ?: "")
    environment("SYNC_API_TOKEN", System.getenv("SYNC_API_TOKEN") ?: "")
}
