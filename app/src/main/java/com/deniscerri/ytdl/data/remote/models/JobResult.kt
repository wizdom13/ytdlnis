package com.deniscerri.ytdl.data.remote.models

import com.google.gson.annotations.SerializedName

data class JobResult(
    val mime: String?,
    @SerializedName("file_name") val fileName: String?,
    @SerializedName("size_bytes") val sizeBytes: Long?,
    @SerializedName("download_url") val downloadUrl: String?
)
