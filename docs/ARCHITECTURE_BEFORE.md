# YTDLnis Architecture — Current On-Device Design

## Overview
YTDLnis is presently delivered as a single Android application module that bundles
`yt-dlp` together with ffmpeg/aria2c binaries via the
[youtubedl-android](https://github.com/yausername/youtubedl-android) wrapper. The app
manages URL ingestion (share intents, clipboard detection, manual entry), queues media
downloads, and persists metadata locally so the user can browse history, retry failures,
and interact with finished files without leaving the app.

## Build & Runtime Configuration
- **Gradle plugins** – `com.android.application`, Kotlin Android/Serialization/Parcelize,
  Kotlin Compose, Google Secrets plugin, and `com.google.devtools.ksp` for Room code
  generation.【F:app/build.gradle†L1-L62】
- **SDK targets** – Min SDK 24, target/compile SDK 35. Java 17 + Kotlin JVM 17 are
  enabled and desugaring is turned on for Java NIO APIs.【F:app/build.gradle†L27-L111】
- **Packaging** – ABI splits are produced for x86/x86_64/armeabi-v7a/arm64-v8a, with
  legacy JNI packaging retained to ship native yt-dlp/ffmpeg binaries.【F:app/build.gradle†L78-L118】
- **Key dependencies** – `io.github.junkfood02.youtubedl-android` (library + ffmpeg +
  aria2c), AndroidX WorkManager, Room (KSP compiler), Paging, Lifecycle, RxAndroid,
  ExoMedia, Picasso, and various Compose/Material libraries.【F:app/build.gradle†L120-L192】
- **Permissions** – INTERNET, broad storage (WRITE/READ/MANAGE), foreground service,
  notifications, alarm scheduling, and media access to support background transfers and
  media library integration.【F:app/src/main/AndroidManifest.xml†L1-L80】

## High-Level Module Layout
```
app/
  src/main/java/com/deniscerri/ytdl/
    App.kt                     ← Application + native lib bootstrap
    MainActivity.kt            ← Single-activity UI shell (fragments, nav graph)
    database/                  ← Room entities, DAOs, repositories, view models
    receiver/                  ← Broadcast/Activity receivers (share sheet, notifications)
    ui/                        ← Fragments, adapters, Compose components
    util/                      ← YTDLP wrappers, notification/file helpers, settings
    work/                      ← CoroutineWorker implementations (downloads, updates)
```

The `App` class initializes YoutubeDL, FFmpeg, and Aria2c in a background coroutine once
the process starts, while also registering notification channels and default
preferences.【F:app/src/main/java/com/deniscerri/ytdl/App.kt†L12-L70】 MainActivity hosts
navigation destinations for queue/history/settings and orchestrates clipboard detection,
share intents, and user prompts around yt-dlp updates.【F:app/src/main/java/com/deniscerri/ytdl/MainActivity.kt†L59-L287】

## Data Persistence & View Models
`DBManager` configures the Room database, exposing DAOs for downloads, results, logs,
command templates, cookies, and history. ViewModels wrap the repositories to expose Flow
streams for paging lists and counters that drive the queue UI.【F:app/src/main/java/com/deniscerri/ytdl/database/DBManager.kt†L1-L160】【F:app/src/main/java/com/deniscerri/ytdl/database/viewmodel/DownloadViewModel.kt†L1-L156】
`DownloadViewModel` also coordinates WorkManager scheduling for download batches and
provides helper methods that serialize user preferences (audio/video formats, command
templates) into WorkManager `Data` objects.【F:app/src/main/java/com/deniscerri/ytdl/database/viewmodel/DownloadViewModel.kt†L157-L240】

## Download Pipeline (On Device)
1. **Queueing** – URLs captured from share intents (`ShareActivity`) or clipboard events
   are converted into `DownloadItem` records and stored with `Queued` status. The
   DownloadViewModel enqueues a unique WorkManager job named `download` that keeps the
   queue active.【F:app/src/main/java/com/deniscerri/ytdl/receiver/ShareActivity.kt†L40-L182】【F:app/src/main/java/com/deniscerri/ytdl/database/viewmodel/DownloadViewModel.kt†L241-L356】
2. **Foreground execution** – `DownloadWorker` is a `CoroutineWorker` that switches to a
   foreground service with custom notifications so Android lets it run indefinitely in
   the background.【F:app/src/main/java/com/deniscerri/ytdl/work/DownloadWorker.kt†L14-L71】
3. **Request construction** – For each eligible `DownloadItem`, the worker uses
   `YTDLPUtil` to translate stored metadata (format, quality, cookies, scheduler
   options, custom command templates) into a `YoutubeDLRequest`.【F:app/src/main/java/com/deniscerri/ytdl/work/DownloadWorker.kt†L105-L208】【F:app/src/main/java/com/deniscerri/ytdl/util/extractors/ytdlp/YTDLPUtil.kt†L724-L780】
4. **yt-dlp invocation** – The worker calls `YoutubeDL.getInstance().execute(request,
   downloadItem.id.toString(), true, progressCallback)` to run the bundled native binary
   in-process. Progress callbacks update the database, send foreground notification
   updates, publish log entries, and honor pause/cancel by destroying the process via the
   youtubedl-android API.【F:app/src/main/java/com/deniscerri/ytdl/work/DownloadWorker.kt†L209-L376】
5. **Post-processing** – When `yt-dlp` finishes, the worker handles file moves/renames,
   playlist item splitting, thumbnail embedding, and queue chaining. Errors are recorded
   to `LogRepository` and user notifications reflect final status.【F:app/src/main/java/com/deniscerri/ytdl/work/DownloadWorker.kt†L377-L640】

Supporting workers cover scheduled source observation, command-template driven terminal
operations, and automatic yt-dlp binary updates.【F:app/src/main/java/com/deniscerri/ytdl/work/ObserveSourceWorker.kt†L118-L220】【F:app/src/main/java/com/deniscerri/ytdl/work/TerminalDownloadWorker.kt†L61-L150】【F:app/src/main/java/com/deniscerri/ytdl/work/UpdateYTDLWorker.kt†L10-L30】 Receivers such as `PauseDownloadNotificationReceiver` and
`CancelDownloadNotificationReceiver` stop the associated YoutubeDL process when users act
from notifications.【F:app/src/main/java/com/deniscerri/ytdl/receiver/PauseDownloadNotificationReceiver.kt†L12-L33】

## UX Layer Touchpoints
- **Share-to & clipboard ingestion** – Dedicated activities/watchers capture incoming
  URLs, pre-fill the download queue, and open the download configuration sheet.
- **Queue & history** – Paging-backed lists surface download status, with actions to
  pause/resume/cancel, open files with external players, share results, or delete.
- **Notifications** – Foreground notifications communicate progress, success/failure,
  and quick actions (pause/cancel/open queue) while WorkManager ensures background
  continuity.【F:app/src/main/java/com/deniscerri/ytdl/util/NotificationUtil.kt†L40-L210】

## Limitations of the Current Approach
Bundling yt-dlp plus ffmpeg/aria2c inflates APK size and forces the app to request broad
storage permissions. Downloads compete with other Android background limits, and the
entire pipeline runs on user devices, which complicates updates, regional network
workarounds, and reuse by other clients. These constraints motivate the move to a
client–server architecture described in the follow-up proposal.
