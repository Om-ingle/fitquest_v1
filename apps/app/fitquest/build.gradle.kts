plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    id("com.google.devtools.ksp")
}

val envProperties: Map<String, String> = run {
    val candidates = listOfNotNull(
        rootProject.file(".env"),
        project.file(".env"),
        rootProject.projectDir.parentFile?.resolve("apps/app/.env"),
        rootProject.projectDir.parentFile?.resolve(".env"),
        file("../.env")
    )
    val envFile = candidates.firstOrNull { it.exists() }
    if (envFile == null) {
        logger.warn(".env file not found in candidates")
        emptyMap()
    } else {
        envFile.readLines()
            .mapNotNull { line ->
                val trimmed = line.trim()
                if (trimmed.isEmpty() || trimmed.startsWith("#") || !trimmed.contains("=")) {
                    null
                } else {
                    val key = trimmed.substringBefore("=").trim()
                    val value = trimmed.substringAfter("=", "").trim()
                    key to value
                }
            }
            .toMap()
    }
}

fun String.cleanEnvValue(): String = trim().trim('"').trim('\'')

fun envOrDefault(name: String, default: String = ""): String {
    val envValue = System.getenv(name)?.cleanEnvValue()
    if (!envValue.isNullOrEmpty()) return envValue

    val fileValue = envProperties[name]?.cleanEnvValue()
    if (!fileValue.isNullOrEmpty()) return fileValue

    return default
}

android {
    namespace = "com.example.mobileapp"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.example.mobileapp"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        val mapTilerApiKey = envOrDefault("MAPTILER_API_KEY")
        val rawStyleUrl = envOrDefault("MAPTILER_STYLE_URL")
        val mapTilerStyleUrl = when {
            rawStyleUrl.isNotEmpty() -> {
                rawStyleUrl.replace("\${MAPTILER_API_KEY}", mapTilerApiKey)
                    .replace("\$MAPTILER_API_KEY", mapTilerApiKey)
            }
            mapTilerApiKey.isNotEmpty() -> {
                "https://api.maptiler.com/maps/streets-v2/style.json?key=$mapTilerApiKey"
            }
            else -> {
                "https://tiles.openfreemap.org/styles/liberty"
            }
        }
        buildConfigField("String", "MAPTILER_API_KEY", "\"$mapTilerApiKey\"")
        buildConfigField("String", "MAPTILER_STYLE_URL", "\"$mapTilerStyleUrl\"")
    }

    // Two backend flavors (same app logic, only the backend URL differs).
    // The base URL field lives in the flavors, NOT defaultConfig, so each
    // variant is pinned by its flavor. Variants: <flavor><buildType>, e.g.
    // railwayDebug / localDebug.
    flavorDimensions += "backend"
    productFlavors {
        create("railway") {
            dimension = "backend"
            // Production: the deployed Railway backend. Deliberately NOT
            // env-overridable (no envOrDefault) so a local .env carrying a
            // LAN IP can never leak into the production APK.
            buildConfigField(
                "String",
                "BACKEND_BASE_URL",
                "\"https://fitquest-api-production.up.railway.app/\"",
            )
        }
        create("local") {
            dimension = "backend"
            // Laptop-LAN fallback: reuses the EXISTING override chain so the
            // laptop IP can be re-supplied on demo day WITHOUT touching
            // source code — set BACKEND_BASE_URL in apps/app/.env (or as an
            // environment variable) and rebuild. Default is the Android
            // emulator's alias for the host's localhost.
            //   emulator:  http://10.0.2.2:8000/
            //   device:    http://<LAPTOP_LAN_IP>:8000/
            val backendBaseUrl = envOrDefault("BACKEND_BASE_URL", "http://10.0.2.2:8000/")
            buildConfigField("String", "BACKEND_BASE_URL", "\"$backendBaseUrl\"")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlinOptions {
        jvmTarget = "11"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)

    // DI and state stack used by the capture feature.
    implementation(libs.koin.android)
    implementation(libs.koin.compose)
    implementation(libs.voyager.screenmodel)
    implementation(libs.voyager.navigator)
    implementation(libs.voyager.tab.navigator)
    implementation(libs.voyager.transitions)
    implementation(libs.voyager.koin)
    implementation(libs.orbit.core)
    implementation(libs.orbit.compose)

    // Sensor/location capture and spatial indexing.
    implementation(libs.google.play.services.location)
    implementation("com.uber:h3-android:4.4.0")
// Note: You can also bump this to "4.4.0" if you want the latest version

    // TODO: Re-enable MapLibre once its Maven repository/version is finalized.

    // Source: https://mvnrepository.com/artifact/org.maplibre.gl/android-sdk
    implementation("org.maplibre.gl:android-sdk:13.0.2")
    // Local persistence for captured hexes.
    implementation(libs.androidx.room.runtime)
    implementation(libs.androidx.room.ktx)
    ksp(libs.androidx.room.compiler)

    // Source: https://mvnrepository.com/artifact/com.squareup.retrofit2/retrofit
    implementation("com.squareup.retrofit2:retrofit:2.9.0")
    implementation("com.squareup.retrofit2:converter-gson:2.9.0")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")

    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    debugImplementation(libs.androidx.compose.ui.tooling)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
}