package com.deniscerri.ytdl.data.remote.models

import com.google.gson.annotations.SerializedName

data class JobResponse(
    val id: String,
    val status: String,
    @SerializedName("created_at") val createdAt: String? = null
)
