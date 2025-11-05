package com.deniscerri.ytdl.data.remote

import android.content.Context
import androidx.preference.PreferenceManager
import com.deniscerri.ytdl.BuildConfig

/**
 * Reads API configuration from shared preferences, falling back to build config values.
 */
object ApiConfig {
    private const val KEY_API_BASE_URL = "api_base_url"
    private const val KEY_API_KEY = "api_key"

    fun getBaseUrl(context: Context): String {
        val prefs = PreferenceManager.getDefaultSharedPreferences(context)
        val value = prefs.getString(KEY_API_BASE_URL, null)?.trim()
        return if (value.isNullOrEmpty()) {
            BuildConfig.API_BASE_URL
        } else {
            value
        }
    }

    fun getApiKey(context: Context): String {
        val prefs = PreferenceManager.getDefaultSharedPreferences(context)
        val value = prefs.getString(KEY_API_KEY, null)?.trim()
        return if (value.isNullOrEmpty()) {
            BuildConfig.API_KEY
        } else {
            value
        }
    }
}
