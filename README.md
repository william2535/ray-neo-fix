# ray-neo-fix
# RayNeo Air 4 Pro Spatial Head Tracking for Android

An experimental open-source Android project that unlocks direct IMU head tracking, head-controlled mouse input and 3DoF spatial screen anchoring on the RayNeo Air 4 Pro.

> **Current release: v0.8 Beta**
>
> This is an independent community project and is not affiliated with or endorsed by RayNeo/TCL.

---

## What is this?

The RayNeo Air 4 Pro is primarily presented as a plug-and-play USB-C display.

This project goes further by communicating directly with the motion sensors inside the glasses.

The Android application reads the Air 4 Pro's IMU data over USB, processes the gyroscope data in real time and converts physical head movement into usable Android input and spatial display movement.

This currently allows the Air 4 Pro to do things such as:

- Head-controlled Android mouse input
- 3DoF head tracking
- Pinning the Android screen in a fixed direction
- Looking away from a pinned display and physically looking back towards it
- Recentring the virtual display
- Creating left/right spatial screen snapshots
- Floating spatial controls over other Android applications

The aim is to turn the Air 4 Pro from a display that simply follows your head into a much more capable experimental spatial-computing display.

No modification to the glasses firmware is required.

---

# Why does this project exist?

Normally, connecting the Air 4 Pro to a compatible device gives you a large virtual display positioned in front of your eyes.

That is useful for gaming and media, but the display effectively travels with your head.

This project experiments with something different.

Instead of:

**Turn head → screen follows you**

the goal is:

**Turn head → screen remains where you placed it**

For example, you can place a screen directly in front of you, turn your head to the left, and the screen moves out of your field of view.

Turn your head back towards its original position and the screen comes back into view.

This creates the impression that the display occupies a position in the world rather than being permanently attached to your face.

The current implementation is **3DoF (three degrees of freedom)**.

It tracks rotational movement:

- Yaw — looking left/right
- Pitch — looking up/down
- Roll — tilting your head

It does **not currently provide 6DoF positional tracking**, so physically walking sideways or moving your head forwards/backwards is not tracked as movement through a 3D environment.

---

# Current Features

## 1. Direct Air 4 Pro IMU access

The application communicates directly with the RayNeo Air 4 Pro over USB.

The glasses provide accelerometer and gyroscope measurements which are decoded by the application.

The sensor stream operates at approximately **118 Hz on the hardware used during development**.

This means head movement can be sampled considerably faster than the Android UI itself needs to refresh.

---

## 2. 3DoF Head Tracking

Gyroscope measurements are converted into:

- Pitch
- Yaw
- Roll

The application integrates angular velocity over time to estimate the orientation of the user's head.

Filtering, deadzone handling and bias correction are applied to make the result usable for interactive head tracking.

---

## 3. Spatial Screen Anchoring

Anchor Mode allows the Android display to behave like a screen positioned in the environment.

Start Anchor Mode and press:

**PIN HERE**

The current head orientation becomes the centre position of the virtual display.

Looking away causes the display to move out of view.

Looking back towards the pinned orientation brings it back.

This is currently rotational anchoring rather than true positional world tracking.

---

## 4. Android Head Mouse

The project can also translate head movement into Android mouse movement.

Move your head:

- Left/right → pointer moves horizontally
- Up/down → pointer moves vertically

This uses a virtual Linux input device exposed through `/dev/uinput`.

The application creates a virtual mouse called:

`RayNeo Head Mouse`

This has been confirmed working on the Android hardware used during development.

### Important

Availability of `/dev/uinput` varies between Android devices and ROMs.

The development handheld allows an ordinary application to access it without root.

Other Android devices may restrict access.

Therefore:

**Head Mouse compatibility is device-dependent.**

The IMU/head-tracking functionality may still work on a device even if the virtual mouse does not.

---

# Spatial Panels

The current experimental spatial desktop provides positions for:

**LEFT | CENTRE | RIGHT**

The centre panel contains the live captured Android display.

Left and right positions can contain captured snapshots.

This means you can place information around yourself and return to it by moving your head.

For example:

**LEFT**
Reference/information

**CENTRE**
Current Android application

**RIGHT**
Another captured screen

This is an early implementation of the larger spatial-desktop idea.

### Important limitation

The left and right panels are currently **snapshots**, not independent live Android applications.

Creating multiple simultaneously live interactive Android surfaces is one of the major goals for future versions.

---

# Floating Controls

v0.8 introduced floating controls so spatial functions can be used while another Android application is open.

The floating bar contains:

`◀ SNAP | PIN | SNAP ▶ | ×`

### ◀ SNAP

Captures the current screen and places the snapshot in the left spatial position.

### PIN

Re-centres/pins the spatial environment around your current head orientation.

### SNAP ▶

Captures the current screen and places the snapshot in the right spatial position.

### ×

Closes the floating control bar.

Android's **Display over other apps** permission is required for the floating controls.

The overlay temporarily hides itself while a snapshot is captured so that the control bar is not included in the captured image.

---

# Installation

## Requirements

You will need:

- RayNeo Air 4 Pro
- Compatible Android host device
- USB connection to the glasses
- Android APK from the Releases page

Your Android device must also be capable of outputting video to the glasses.

The tracking functionality requires Android to expose the RayNeo USB device to the application.

---

## Installing the beta

1. Download the latest release.

2. If the download is provided as a ZIP, extract it.

3. Locate the `.apk` file.

4. Open the APK.

5. Android may ask you to enable:

   **Install unknown apps**

6. Allow installation for your browser/file manager.

7. Install the application.

8. Connect the RayNeo Air 4 Pro.

9. Open the app.

---

# First Setup

## Step 1 — Connect the glasses

Connect the Air 4 Pro to your Android device.

The normal RayNeo display should activate.

---

## Step 2 — Start Tracking

Open the application and select:

**START TRACKING**

Android should display a USB permission prompt.

Allow the application to access the RayNeo device.

---

## Step 3 — Keep still during calibration

Keep your head reasonably still while the initial gyroscope bias is established.

Gyroscopes never read exactly zero when stationary.

The application therefore measures the stationary output and treats this as sensor bias.

Correct calibration significantly reduces unwanted movement/drift.

---

## Step 4 — Check tracking

The application displays live tracking information including:

- Pitch
- Yaw
- Roll
- Temperature
- Frame count

Move your head and verify that the orientation values respond.

If these values update, the application is receiving IMU packets from the glasses.

---

# Using Head Mouse

Enable:

**Mouse**

Head movement should now move the Android pointer on compatible devices.

Several controls can be adjusted.

## Sensitivity

Controls how far the pointer moves for a given amount of head movement.

Higher values create faster cursor movement.

## Deadzone

Ignores extremely small gyroscope measurements.

Increasing the deadzone can reduce unwanted cursor movement while your head is stationary.

Too much deadzone will make small intentional movements harder.

## Smoothing

Controls filtering of the gyroscope signal.

More smoothing can make movement calmer but introduces additional latency.

Less smoothing feels more immediate but may expose more sensor noise.

## Invert X / Y

Reverses movement on the corresponding axis if required.

## Recalibrate

Recalculates the stationary gyro bias.

Keep the glasses still when recalibrating.

## Recenter

Resets the current integrated orientation to the centre position.

---

# Using Anchor Mode

Once head tracking is running:

1. Select **START ANCHOR MODE**.

2. Android will request screen-capture permission.

3. Allow screen capture.

4. The application creates the spatial display.

5. Look directly towards where you want the virtual screen centred.

6. Select:

   **PIN HERE**

7. Slowly turn your head left or right.

The screen should remain associated with its pinned direction instead of simply remaining centred in your vision.

---

# Anchor Axis Settings

Different display/orientation configurations can require axis inversion.

On the hardware used during development, the configuration confirmed working correctly is:

**Invert Anchor X: ON**

**Invert Anchor Y: ON**

This is currently the recommended configuration for the tested setup.

---

# How the Tracking Works

The Air 4 Pro exposes a USB HID interface.

During development the following USB identifiers were observed:

```
VID: 0x1BBB
PID: 0xAF50
```

The application claims HID interface 0 and enables the sensor stream using a HID control transfer.

The enable payload used is:

```
66 01
```

Sensor packets begin with:

```
99 65 40 00
```

The sensor payload contains seven little-endian IEEE-754 float32 values.

Current decoded structure:

| Offset | Value |
|-------:|-------|
| 4 | Accelerometer X |
| 8 | Accelerometer Y |
| 12 | Accelerometer Z |
| 16 | Gyroscope X |
| 20 | Gyroscope Y |
| 24 | Gyroscope Z |
| 28 | Temperature |

The head axes discovered during testing are currently mapped as:

```
Pitch = gyroX
Yaw   = gyroY + gyroZ
Roll  = gyroY - gyroZ
```

This protocol information was determined experimentally and may change with different hardware/firmware revisions.

---

# Sensor Processing

Raw gyroscope measurements cannot simply be mapped directly to screen movement.

The tracker performs several stages of processing.

## Bias correction

A stationary gyroscope still reports small angular velocities.

During calibration the application determines this offset and subtracts it from future measurements.

The tracker can also gradually adapt the bias while the glasses remain stationary.

## Deadzone

Very small measurements are ignored to reduce visible jitter and drift.

## Smoothing

A low-pass style filter reduces rapid sensor noise.

Conceptually:

```
filteredRate =
    previousRate * smoothing
    + correctedRate * (1 - smoothing)
```

## Orientation integration

A gyroscope measures angular velocity rather than absolute orientation.

Orientation is estimated by integrating that velocity over time:

```
angle += angularVelocity * deltaTime
```

This produces the pitch/yaw/roll orientation used by the spatial renderer.

Because this is gyro integration rather than absolute optical/world tracking, gradual drift can occur.

Recentring and bias adaptation help compensate for this.

---

# Performance

An important discovery during development was that sensor frequency and UI update frequency must remain separate.

The Air 4 Pro sensor stream was observed at roughly:

**118 sensor frames per second**

An early Android implementation accidentally passed orientation to Anchor Mode through a status broadcast updated only approximately every 100 ms.

That effectively reduced visual tracking to around:

**10 Hz**

even though the glasses themselves were producing data much faster.

This caused obvious choppiness.

The current implementation instead exposes the newest orientation to the spatial renderer continuously.

The display renderer reads the newest available pose on each Android display frame using Android's frame scheduling.

This produced the significantly smoother tracking used by the current beta.

---

# Screen Capture / Spatial Rendering

Anchor Mode uses Android's MediaProjection system to capture the Android display.

The captured surface is displayed through a separate presentation associated with the external display.

Head orientation changes the position of the rendered content relative to a larger virtual world/canvas.

Conceptually:

```
Air 4 Pro IMU
      ↓
USB HID
      ↓
Raw accelerometer + gyro
      ↓
Bias correction
      ↓
Deadzone
      ↓
Filtering
      ↓
Pitch / Yaw / Roll
      ↓
Android frame renderer
      ↓
Spatial world offset
      ↓
RayNeo external display
```

The glasses themselves are therefore not being flashed or modified.

All experimental spatial processing occurs on the connected Android host.

---

# Does This Flash the Glasses?

**No.**

Nothing is flashed to the RayNeo Air 4 Pro.

The project does not currently modify:

- RayNeo firmware
- bootloader
- display firmware
- permanent glasses settings

The app communicates with the glasses while connected.

Uninstalling the Android application removes the software from the Android device.

---

# Root / Termux

The original protocol investigation was performed using Python/Termux tools.

The Android application replaces that development environment.

For the current tested configuration:

**Root: Not required**

**Termux: Not required**

The APK handles USB communication and tracking itself.

---

# Compatibility

## Confirmed

### RayNeo Air 4 Pro

Direct IMU communication and tracking have been confirmed on the development pair.

### Development Android hardware

The complete pipeline has been confirmed including:

- USB access
- IMU decoding
- ~118 Hz sensor polling
- head tracking
- filtering
- 3DoF anchoring
- MediaProjection
- external Presentation rendering
- floating controls
- `/dev/uinput` virtual mouse

---

## Not yet confirmed

The project has not yet been widely tested across:

- different Android manufacturers
- different Android versions
- different Air 4 Pro firmware versions
- other RayNeo Air models

Do not assume compatibility simply because another model looks similar.

---

# Testing on Another Device

External testing is extremely useful.

If you try the application, please report:

**Glasses**
- Exact RayNeo model
- Firmware version if known

**Android device**
- Manufacturer
- Model
- Android version

**Results**
- Does Android detect the glasses?
- Does the app request USB permission?
- Does the frame counter increase?
- Do pitch/yaw/roll change?
- Does Head Mouse work?
- Does Anchor Mode launch?
- Is the external RayNeo display detected?
- Does PIN HERE work?
- Do floating controls work?
- Does SNAP LEFT work?
- Does SNAP RIGHT work?
- Does stopping Anchor Mode work correctly?

Please include any error messages.

---

# Known Limitations

This is an experimental beta.

Current limitations include:

### 3DoF only

Rotation is tracked.

Physical positional movement through the room is not.

### Gyroscope drift

The current system integrates angular velocity.

Long sessions can therefore accumulate orientation error.

### Device-specific `/dev/uinput`

Head Mouse may not work on Android systems that restrict access to `/dev/uinput`.

### Side panels are snapshots

LEFT and RIGHT are currently captured images rather than continuously running Android surfaces.

### Android capture restrictions

Some protected/DRM applications may refuse screen capture or display black content.

### Limited hardware testing

The current beta has been developed and validated primarily on one Air 4 Pro + Android hardware combination.

---

# Roadmap

This project is still at an early stage.

## Near-term

- Test more Android devices
- Test additional Air 4 Pro firmware versions
- Improve calibration
- Reduce long-term gyro drift
- Improve error messages
- Improve first-run setup
- Better automatic USB reconnection
- Cleaner spatial controls
- Save user settings between sessions

## Spatial Desktop

One of the main goals is replacing snapshot panels with genuinely live spatial surfaces.

The intended experience is closer to:

```
      LEFT APP       CENTRE APP       RIGHT APP
          \              |               /
           \             |              /
            \            |             /
                    USER
```

Instead of moving between applications on one screen, applications could occupy different directions around the user.

You would physically look towards the application you want.

## Longer-term research

Possible areas include:

- Multiple live spatial panels
- Persistent panel locations
- Better orientation correction
- Alternative absolute orientation references
- Improved roll support
- Gesture/controller interaction
- Spatial application launcher
- Automatic calibration
- More RayNeo hardware support
- Compatibility database
- Easier installation/update process

True 6DoF would require additional positional information beyond the current gyroscope-based solution and should be considered a separate research problem rather than a promised feature.

---

# Project Status

**v0.8 Beta**

The important parts now work on the original development hardware.

This includes the full chain:

```
RayNeo Air 4 Pro
        ↓
Direct USB IMU access
        ↓
~118 Hz sensor data
        ↓
Android native tracker
        ↓
Pitch / Yaw / Roll
        ↓
        ├── Head Mouse
        │
        └── Spatial Anchor
                ↓
        Floating controls
                ↓
        LEFT / CENTRE / RIGHT workspace
```

The next phase is discovering how portable this implementation is across other people's Android hardware.

---

# Contributing / Testing

Testing is currently more valuable than anything else.

If you own an Air 4 Pro and an Android device capable of driving the glasses, try the latest beta and report exactly what works and what doesn't.

Protocol investigation, Android development and improvements to the spatial renderer are also welcome.

Please open a GitHub Issue for reproducible bugs rather than only reporting them in Reddit comments.

---

# Disclaimer

This is experimental third-party software.

It is not an official RayNeo application and is not affiliated with RayNeo or TCL.

Use it at your own risk.

The USB protocol information documented here was determined experimentally during development and should not be considered official RayNeo protocol documentation.