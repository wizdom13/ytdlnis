package com.deniscerri.ytdl.data.remote

import android.content.Context
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

object ApiClient {
    @Volatile
    private var api: YtdlApi? = null

    fun get(context: Context): YtdlApi {
        val existing = api
        if (existing != null) {
            return existing
        }

        synchronized(this) {
            val cached = api
            if (cached != null) {
                return cached
            }

            val authInterceptor = Interceptor { chain ->
                val original = chain.request()
                val apiKey = ApiConfig.getApiKey(context)
                val request: Request = original.newBuilder()
                    .header("Authorization", "Bearer $apiKey")
                    .build()
                chain.proceed(request)
            }

            val logging = HttpLoggingInterceptor().apply {
                level = HttpLoggingInterceptor.Level.BASIC
            }

            val client = OkHttpClient.Builder()
                .addInterceptor(authInterceptor)
                .addInterceptor(logging)
                .connectTimeout(30, TimeUnit.SECONDS)
                .readTimeout(30, TimeUnit.SECONDS)
                .build()

            val retrofit = Retrofit.Builder()
                .baseUrl(ApiConfig.getBaseUrl(context))
                .addConverterFactory(GsonConverterFactory.create())
                .client(client)
                .build()

            val created = retrofit.create(YtdlApi::class.java)
            api = created
            return created
        }
    }
}
