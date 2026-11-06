// :core — pure Kotlin/JVM. No Android dependency, so the sequencer, player and device
// state machine run under JUnit on a fake clock, and `installDist` yields the
// conformance player (`build/install/core/bin/core`).
plugins {
    id("org.jetbrains.kotlin.jvm")
    id("org.jetbrains.kotlin.plugin.serialization")
    application
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    testImplementation(kotlin("test"))
}

application {
    applicationName = "core"
    mainClass.set("ziv.core.MainKt")
}

tasks.test {
    useJUnit()
    testLogging {
        events("failed", "skipped")
        showStandardStreams = false
        exceptionFormat = org.gradle.api.tasks.testing.logging.TestExceptionFormat.FULL
    }
}
