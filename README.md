# uefn-device-graph
Visual node graph for UEFN devices. Scans your level and parses Verse code to map every connection between devices.

# UEFN Device Node Graph

Visual blueprint-style node graph for Fortnite Creative (UEFN) devices.

Python tool that runs inside the UEFN editor. Scans your level and parses Verse code to visualize every connection between devices.

## How to Run

1. Enable Python Editor Scripting in UEFN (Editor Preferences > Experimental)
2. Save `node_graph.py` to your project's Content folder
3. Open the Output Log Python REPL and run: exec(open(r"YOUR_PROJECT_PATH\Content\node_graph.py").read())
4. Click SCAN LEVEL

## Features

- Scans all devices in your level automatically
- Parses Verse files for @editable references, event subscriptions, and function calls
- Visual node graph with draggable nodes and colored connections
- Click a node to select the device in viewport (press F to fly to it)
- Flags broken connections (red) and orphan devices (yellow)
- Shows unused Verse functions
- Open Verse files in VS Code with one click
- Search and filter by device type
- Zoom in/out
- Add notes to devices
- Export graph as text summary
- Re-scan preserves node positions

- ## Disclaimer

I'm new to building tools like this. This is a first version to get the community started. There will be bugs. I can't promise regular updates or support.

If you find issues, feel free to open a PR. If you want to fork it and make it better, go for it.

Built with Python inside UEFN's experimental scripting environment. This feature is experimental and could change or break with future UEFN updates.

Use at your own risk. This tool does not modify your project files, it only reads your level and Verse code.
