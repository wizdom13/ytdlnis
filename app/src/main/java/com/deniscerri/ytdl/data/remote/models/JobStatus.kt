package com.deniscerri.ytdl.data.remote.models

import com.google.gson.annotations.SerializedName

data class JobStatus(
    val id: String,
    val status: String,
    val progress: Int? = null,
    val result: JobResult? = null,
    val error: String? = null,
    @SerializedName("updated_at") val updatedAt: String? = null
)
