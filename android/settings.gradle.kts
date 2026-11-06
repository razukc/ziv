// The Ziv native phone renderer (docs/ARCHITECTURE.md §5.4).
//   :core  pure Kotlin/JVM — spec, sequencer, player, device state machine, wire frames,
//          and the conformance player (`installDist` -> build/install/core/bin/core)
//   :app   the Android app — foreground service, OkHttp socket, Vibrator, SQLite queue, the wearer's screen
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "ziv-android"
include(":core", ":app")
