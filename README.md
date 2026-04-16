# EDMC-Raven-Colonial-Plugin
This plugin for EDMC allows you to update and keep track of projects on Raven Colonial, similar to how SRV survey does, but this works on Linux, this also means you only need 1 program running in the background for colonization instead of 2.


# Features:

Link Projects: Instantly link to planned or active construction sites in your current system.

Initialize New Colonies: Deploy new colony projects directly from the EDMC interface based on your docked location.

In-Game Overlay (HUD): * Track your current system, active project demands, and jump information.
  Fully customizable: Adjust scale, opacity (background and text), text alignment, and colors, with an Auto-hide functionality to keep your screen clutter-free.
  
EDSM Integration: Automatically polls EDSM for the current system to generate a "Colonial Report," highlighting prime bodies, terraformable planets, and geological/biological signal counts.

Fleet Carrier & Ship Sync: Automatically updates the Raven Colonial database with your current ship's cargo capacity and your Fleet Carrier's market data/jumps.

Streamlined UI: Easily hide the "Tools & Debug" or "Project Actions" tabs to keep your EDMC window minimal.


# How To Install:


1. Download the latest release of this plugin.

2. Open EDMC and go to File -> Settings -> Plugins.

3. Click the Open button to open the plugins folder.

4. Extract the RavenColonialSync folder from the downloaded archive into the EDMC plugins directory.

5. Restart EDMC. The plugin should now appear in the main EDMC window.
   

# HUD & Overlay Settings:


HUD Text Color / Layout Columns: Customize the look and organization of the commodity demand lists.

Opacity & Scale: Fine-tune the transparency and size of the overlay to fit your screen resolution.

Auto-Hide HUD: Set a timer (in seconds) for the HUD to disappear after updating. Set to 0 to keep it visible continuously.

Show Jump Info: Toggle system jump details (Population, Economy, Security).

HUD Always on Top: Keep the overlay forced above the Elite Dangerous game client (Highly recommended for Borderless/Windowed mode).


# UI Preferences:


Hide Tools & Debug Tab: Removes the tools section from the EDMC main window.

Hide Project Actions Tab: Removes the initialization and linking buttons from the EDMC main window for a cleaner look when you only want to run background syncs.


# Usage:


Undocked / Exploring: The plugin will automatically track your jumps and scan data. If EDSM data is available for your current system, you can click System Colonial Report to view potential colonization targets.

Starting a Project: Dock at a station or construction site, open the EDMC window, and click Initialize New Colony or Link Planned/Active Colony.

Syncing Progress: To capture the exact commodity requirements due to in-game variance, you must physically view the market board in-game. The plugin will intercept the market data and sync it to the cloud.


# Troubleshooting & Debugging:


If the plugin isn't syncing properly:

Ensure your API Key is correct in the settings.

Ensure you have opened the Market Board in-game at least once while docked.

Click View Plugin Debug Log in the EDMC UI (if the Tools tab is not hidden) to see the live internal memory log for errors.

The plugin automatically writes a detailed debug log to ~/raven_debuglog.md (or your system's temp directory) if you need to report an issue.
