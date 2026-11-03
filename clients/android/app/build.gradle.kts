plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "eu.sparkhat.aioa.companion"
    compileSdk = 36
    buildToolsVersion = "35.0.0"
    defaultConfig {
        applicationId = "eu.sparkhat.aioa.companion"
        minSdk = 26
        targetSdk = 36
        versionCode = 4
        versionName = "0.3.1-cosmic"
    }
    buildFeatures { compose = true; buildConfig = true }
    defaultConfig {
        val source = providers.environmentVariable("AIOA_BUILD_SOURCE_SHA").orElse("UNBOUND").get()
        require(source == "UNBOUND" || Regex("[0-9a-f]{40}").matches(source))
        buildConfigField("String", "AIOA_SOURCE_SHA", "\"$source\"")
    }
    buildTypes {
        create("cosmic4") {
            initWith(getByName("debug"))
            applicationIdSuffix = ".cosmic4"
            matchingFallbacks += listOf("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
androidComponents {
    onVariants(selector().withBuildType("cosmic4")) { variant ->
        variant.outputs.forEach { output ->
            output.versionCode.set(401)
            output.versionName.set("4.1.0-cosmic")
        }
    }
}
kotlin { jvmToolchain(17) }

dependencies {
    implementation("com.google.android.gms:play-services-code-scanner:16.1.0")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.compose.ui:ui:1.9.0")
    implementation("androidx.compose.foundation:foundation:1.9.0")
    implementation("androidx.compose.material3:material3:1.3.2")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.4")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.9.4")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.4")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    testImplementation("junit:junit:4.13.2")
}
