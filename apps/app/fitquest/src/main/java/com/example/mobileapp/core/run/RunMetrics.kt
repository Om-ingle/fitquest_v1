package com.example.mobileapp.core.run

/**
 * Single source of truth for the step-derivation constants the app uses for
 * distance and calories. Kept in one place so the live HUD, the foreground
 * service notification/checkpoint and the finish path can never disagree.
 *
 * Values mirror the existing implementation (see CaptureScreenModel):
 *   distance = steps * 0.75 m,  calories = steps * 0.04 kcal.
 */
object RunMetrics {
    const val METERS_PER_STEP = 0.75
    const val CALORIES_PER_STEP = 0.04

    fun distanceMeters(steps: Int): Double = steps * METERS_PER_STEP

    fun calories(steps: Int): Int = (steps * CALORIES_PER_STEP).toInt()
}
