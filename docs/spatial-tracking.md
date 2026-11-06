# Keeping a pinned screen at the same height

RayNeo Spatial v0.9.13 LAB uses the Air 4 Pro’s accelerometer and gyroscope together. The design target is a screen that stays in the direction where you pinned it as you look around. The most revealing checks are a stationary hold, a slow nod and a return to the original pose.

## Try it on the glasses

1. Start tracking with the glasses upright, approximately level and facing forward. Rest them on a firm support or hold your head still until calibration finishes. Then start the anchor and select **Pin here**.
2. For the drift measurement, leave the glasses on a support and operate the Android device separately. Under **Spatial Desktop → Live diagnostics**, tap **Measure drift**. Keep the glasses still and that screen open for 60 seconds. Record the signed pitch and yaw changes and the screen Y displacement. Positive screen Y is down. The pixel figure is calculated from pose, display height and the app’s vertical field of view.
3. Repeat after the glasses have warmed up for ten minutes. A repeated climb in the same direction is more informative than a single reading. A useful initial target for a supported 1080p bench test is under 0.25° of pitch change in a minute, about 10 pixels. This is a proposed engineering target. Performance on the physical glasses still needs measuring.
4. Wear the glasses and pin at eye level. Nod slowly, hold that angle, then return to the same physical target. Repeat while turning left and right. Watch whether the panel follows gentle motion immediately, settles at the held angle and returns to the mark. A physical mark and a repeatable support give a stronger comparison between builds.
5. If the panel still climbs, record the two 60-second results, whether **Gravity correction active** was visible while stationary, whether yaw moved too, the display resolution and the device model. If the picture moves but the reported pitch and camera Y stay steady, the next investigation is the display/compositor path. A moving pitch reading with a fixed pin points upstream to the sensor estimates.

The one-minute test measures endpoint change. It cannot detect motion that returns to its starting point, measure motion-to-photon latency or distinguish a moving pair of glasses from sensor drift.

## Where the old error entered

The app’s USB report contains acceleration at bytes 4, 8 and 12 in m/s² and angular velocity at bytes 16, 20 and 24 in degrees/s, all little-endian floats. Our hardware notes describe a sampled rate of about 118 Hz. The sensor report has no verified device timestamp in this decoder, so the app uses monotonic host time between accepted packets. [Device measurements and packet examples](../rayneo-protocol-notes.html)

Version 0.9.12 integrated three independently mapped, smoothed gyro rates after the mouse deadzone. No measurement pulled an accumulated pitch error back towards physical vertical. Motion below the mouse deadzone could also be lost, including part of a slow return to the original pose. The renderer then converted the pitch difference from the pinned angle into vertical pixels. With its 27° vertical mapping and a 1080-pixel display, each degree of pitch error moves the panel about 40 pixels. These are identifiable error paths. A trace from the affected glasses is needed to establish which one caused a particular climb.

## What changed in the tracker

| Stage | Implementation | Effect on the pinned screen |
| --- | --- | --- |
| Startup | Collect at least 30 contiguous samples covering 1.5 seconds. Check gyro magnitude, change since the start of the window, approximate 1 g, acceleration stability and timing gaps. Average the accepted raw gyro and gravity vectors. | Movement or broken packets restart the window. An offset measured while moving would be applied to every subsequent frame. |
| Rotation | Subtract the measured gyro bias and integrate the raw three-axis body rate into a unit quaternion. Convert degrees to radians for integration and use the measured time step. | Compound turns use a single orientation. Small deliberate rotations reach the spatial tracker even if the mouse deadzone would discard them. |
| Tilt correction | Predict the direction of gravity in the sensor frame, compare it with the normalised accelerometer vector and feed the angular error back into the orientation. A slower integral term estimates residual tilt bias when the measurement is trusted and the rotation rate is modest. | The gyro responds immediately to a nod. Gravity pulls accumulated pitch and roll error towards the actual held attitude, including when the user holds a non-level pose. |
| Acceleration rejection | Use gravity feedback only for plausible magnitudes (9.1–10.5 m/s²) and normally within 12° of the predicted direction. After a large mismatch, 1.5 seconds of consistent, near-1-g direction at low angular rate allows gradual reacquisition. | A quick shove or bump has less influence on screen tilt. The gyro carries the estimate while gravity is rejected. Prolonged smooth acceleration can still mimic a tilt. |
| Screen coordinates | Rotate the fixed viewing direction into the reference frame. Compute elevation relative to gravity, horizontal heading from the projected look direction and a continuous yaw through the ±180° boundary. Only the camera offset wraps relative to the pin, so a full turn brings the panel back into view. Recentre changes the displayed origin. | Turning in place while looking slightly up should preserve elevation. Near a straight-up or straight-down gaze, heading becomes ill-defined and is held. |
| Mouse output | Apply the existing pitch and yaw mapping, inversion, deadzone, smoothing and fractional-pixel carry on the mouse path. | Gravity feedback can adjust the pinned screen without injecting mouse movement into another app. |

At startup the app waits up to 12 seconds for a usable calibration, then offers a retry. If you recalibrate while tracking, the old estimate continues during the attempt. A successful recalibration updates the gyro bias while preserving the pin. A failed attempt leaves the previous calibration active.

The mounting model uses X for the lateral nod axis. The nominal vertical axis in the sensor Y/Z plane uses the measured yaw-sweep ratio of about 0.28. This is a model from one measured pair. A different unit or firmware may need another mounting transform. Gravity polarity is aligned during an upright startup. Starting with the glasses upside down or pointing straight overhead is unsuitable for checking axis signs.

The filter is a gravity-referenced complementary observer with proportional and integral feedback. Its gains and rejection limits are lab tuning choices. The research basis is the six-axis attitude observer described by Mahony, Hamel and Pflimlin and the acceleration-rejection approach documented by x-io. [Observer paper](https://doi.org/10.1109/TAC.2008.923738) · [x-io Fusion algorithm](https://github.com/xioTechnologies/Fusion#ahrs-algorithm)

## Replay results and limits

The regression suite synthesises rotations and matching gravity vectors independently of the estimator. It checks both pitch directions, a held tilt, roll, yaw over a full turn, acceleration rejection, interrupted startup, irregular timing and multiple sample rates. The source ZIP contains the harness and commands under `tests/`.

| Synthetic input at 118 Hz | v0.9.12 | v0.9.13 |
| --- | ---: | ---: |
| A 6° nod over six seconds, default 2°/s mouse deadzone | 0.00° reported pitch | 6.00° reported pitch |
| 60 seconds of yaw at 6°/s with +0.5°/s injected pitch bias, true pitch fixed, old deadzone set to zero | 30.00° final pitch error | Under 0.01° final error, about 0.19° peak |

The bias test deliberately sets the old deadzone to zero to expose the integration error. It does not say that the stock build normally climbs 30° per minute. Neither test measures USB latency, temperature behaviour on a particular pair, or visible movement through the optics.

The current renderer smooths the pose on display frames with an exponential time constant of about 33 ms. That is a software parameter, not measured end-to-end latency. A delayed response while moving and a gradual climb while motionless need different tests. The commercial comparison is a **direction-pinned 3DoF screen**. Gravity constrains two tilt axes. Rotation about gravity produces no change in that measurement, so absolute yaw still needs an independent heading reference. The verified input path also has no external position reference for following the wearer around a room. A commercial-equivalence claim would need through-the-lens drift, jitter and motion-to-photon measurements under the same movements, hardware setup and display mode. [Android orientation reference](https://developer.android.com/develop/sensors-and-location/sensors/sensors_position#sensors-pos-gamerot) · [XREAL’s 3DoF and 6DoF anchor modes](https://tutorials.xreal.com/docs/glasses/pro-plus/spatial-screen/display-modes/)
