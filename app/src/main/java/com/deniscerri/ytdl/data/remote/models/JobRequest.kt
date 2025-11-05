package com.deniscerri.ytdl.data.remote.models

import com.google.gson.annotations.SerializedName

data class JobRequest(
    val url: String,
    val format: String? = null,
    @SerializedName("prefer_audio") val preferAudio: Boolean? = null,
    val filename: String? = null,
    val headers: Map<String, String>? = null,
    val proxy: String? = null
)
