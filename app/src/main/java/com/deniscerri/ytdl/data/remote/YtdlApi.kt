package com.deniscerri.ytdl.data.remote

import com.deniscerri.ytdl.data.remote.models.JobRequest
import com.deniscerri.ytdl.data.remote.models.JobResponse
import com.deniscerri.ytdl.data.remote.models.JobStatus
import retrofit2.Call
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path

interface YtdlApi {
    @POST("/api/jobs")
    fun createJob(@Body request: JobRequest): Call<JobResponse>

    @GET("/api/jobs/{id}")
    fun getJob(@Path("id") id: String): Call<JobStatus>
}
