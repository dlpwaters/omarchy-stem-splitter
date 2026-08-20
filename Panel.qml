import QtQuick
import QtQuick.Controls as QQC
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "io.github.dlpwaters.stem-splitter"
  ipcTarget: "io.github.dlpwaters.stem-splitter"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color background: bar ? bar.background : Color.background
  readonly property color muted: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.60)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property string helperPath: String(Qt.resolvedUrl("stem-tool")).replace(/^file:\/\//, "")
  readonly property int desiredWidth: Style.space(500)
  readonly property int maximumHeight: Style.space(760)

  property string inputPath: ""
  property string mode: "remove"
  property string outputFormat: "flac"
  property bool removeVocals: true
  property bool removeDrums: false
  property bool removeBass: false
  property bool removeOther: false
  property bool engineReady: false
  property bool busy: actionProc.running
  property bool cancelRequested: false
  property string actionKind: ""
  property string status: "checking"
  property string statusMessage: "Checking the local engine…"
  property string actionError: ""
  property string outputPath: ""
  property int progress: 0

  readonly property string inputName: inputPath === ""
    ? "No track selected"
    : inputPath.split("/").pop()
  readonly property int selectedCount: (removeVocals ? 1 : 0)
    + (removeDrums ? 1 : 0) + (removeBass ? 1 : 0) + (removeOther ? 1 : 0)
  readonly property bool selectionValid: mode === "full"
    || (selectedCount > 0 && selectedCount < 4)

  function open() {
    root.controller.show()
    if (!actionProc.running) checkEngine()
  }

  function close() { root.controller.hide() }
  function toggle() { root.opened ? close() : open() }
  function closeForPopoutSwitch() {
    root.popoutSwitchClosing = true
    close()
  }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.hostWidget || root, direction)
    return false
  }

  function selectedTargets() {
    var targets = []
    if (removeVocals) targets.push("vocals")
    if (removeDrums) targets.push("drums")
    if (removeBass) targets.push("bass")
    if (removeOther) targets.push("other")
    return targets.join(",")
  }

  function checkEngine() {
    if (checkProc.running || actionProc.running) return
    checkProc.running = true
  }

  function chooseFile() {
    if (!selectProc.running && !actionProc.running) selectProc.running = true
  }

  function startSetup() {
    if (actionProc.running) return
    actionKind = "setup"
    cancelRequested = false
    actionError = ""
    outputPath = ""
    progress = 4
    status = "working"
    statusMessage = "Creating the isolated audio engine…"
    actionProc.command = [helperPath, "setup"]
    actionProc.running = true
  }

  function startProcessing() {
    if (actionProc.running || !engineReady || inputPath === "" || !selectionValid) return
    actionKind = "run"
    cancelRequested = false
    actionError = ""
    outputPath = ""
    progress = 2
    status = "working"
    statusMessage = "Preparing the track…"
    actionProc.command = [helperPath, "run", "--mode", mode,
      "--targets", selectedTargets(), "--format", outputFormat, "--", inputPath]
    actionProc.running = true
  }

  function cancelProcessing() {
    if (!actionProc.running) return
    cancelRequested = true
    actionProc.running = false
    status = "idle"
    statusMessage = "Cancelled. No output was published."
    progress = 0
  }

  function processFile(path, requestedMode, targets) {
    processFileAs(path, requestedMode, targets, "flac")
  }

  function processFileAs(path, requestedMode, targets, requestedFormat) {
    inputPath = String(path || "")
    if (requestedMode === "full") mode = "full"
    else mode = "remove"
    var normalizedFormat = String(requestedFormat || "flac").toLowerCase()
    outputFormat = normalizedFormat === "wav" || normalizedFormat === "mp4"
      ? normalizedFormat : "flac"
    var requested = String(targets || "vocals").split(",")
    removeVocals = requested.indexOf("vocals") >= 0
    removeDrums = requested.indexOf("drums") >= 0
    removeBass = requested.indexOf("bass") >= 0
    removeOther = requested.indexOf("other") >= 0
    open()
    if (engineReady) Qt.callLater(startProcessing)
  }

  function applyCheck(line) {
    var parts = String(line || "").trim().split("\t")
    engineReady = parts[0] === "READY"
    status = engineReady ? "idle" : "missing"
    statusMessage = parts.length > 1 ? parts.slice(1).join(" ")
      : (engineReady ? "Ready" : "Audio engine setup is required.")
  }

  function applySelection(exitCode, text) {
    if (exitCode === 0) {
      inputPath = String(text || "").trim()
      outputPath = ""
      status = engineReady ? "idle" : "missing"
      statusMessage = engineReady ? "Ready to process." : "Set up the audio engine first."
    }
  }

  function handleActionLine(line) {
    var parts = String(line || "").trim().split("\t")
    if (parts[0] === "EVENT") {
      progress = Math.max(0, Math.min(100, Number(parts[1]) || 0))
      statusMessage = parts.slice(2).join(" ")
    } else if (parts[0] === "DONE") {
      outputPath = parts.slice(1).join("\t")
      progress = 100
    } else if (parts[0] === "READY") {
      engineReady = true
      progress = 100
      statusMessage = parts.slice(1).join(" ")
    }
  }

  function finishAction(exitCode) {
    if (cancelRequested) {
      cancelRequested = false
      return
    }
    if (exitCode === 0) {
      if (actionKind === "setup") {
        engineReady = true
        status = "ready"
        statusMessage = "Engine ready. Choose a track to begin."
      } else {
        status = "ready"
        statusMessage = "Finished. Your files are on the Desktop."
      }
      progress = 100
      return
    }
    status = "error"
    progress = 0
    var message = String(actionError || "The operation failed.").trim()
    var lines = message.split("\n")
    statusMessage = lines.length > 0 ? lines[lines.length - 1] : message
  }

  function openOutput() {
    if (outputPath !== "" && !openProc.running) {
      openProc.command = [helperPath, "open", outputPath]
      openProc.running = true
    }
  }

  Process {
    id: checkProc
    command: [root.helperPath, "check"]
    stdout: SplitParser { onRead: function(line) { root.applyCheck(line) } }
    onExited: function(exitCode) {
      if (exitCode !== 0 && !root.engineReady) {
        root.status = "missing"
        root.statusMessage = "Audio engine setup is required."
      }
    }
  }

  Process {
    id: selectProc
    command: [root.helperPath, "select"]
    stdout: StdioCollector {
      id: selectOutput
      waitForEnd: true
    }
    onExited: function(exitCode) { root.applySelection(exitCode, selectOutput.text) }
  }

  Process {
    id: actionProc
    stdout: SplitParser { onRead: function(line) { root.handleActionLine(line) } }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.actionError = text
    }
    onExited: function(exitCode) { root.finishAction(exitCode) }
  }

  Process { id: openProc }

  KeyboardPanel {
    id: stemPanel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: keyCatcher
    contentWidth: stemPanel.fittedContentWidth(root.desiredWidth)
    contentHeight: stemPanel.fittedContentHeight(contentColumn.implicitHeight, root.maximumHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: contentColumn
        width: parent.width
        spacing: Style.space(12)

        Row {
          width: parent.width
          spacing: Style.space(12)

          Text {
            text: "󰝚"
            color: Color.accent
            font.family: root.fontFamily
            font.pixelSize: Style.font.display
          }

          Column {
            width: parent.width - Style.space(58)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            Text {
              width: parent.width
              text: "Stem Splitter"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
            }

            Text {
              text: "LOCAL · PRIVATE · NO UPLOAD"
              color: root.muted
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
              font.letterSpacing: 1.0
            }
          }
        }

        Rectangle {
          width: parent.width
          height: Style.space(70)
          radius: Style.cornerRadius
          color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.06)
          border.width: Style.spacing.hairline
          border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.14)

          Row {
            anchors.fill: parent
            anchors.margins: Style.space(10)
            spacing: Style.space(10)

            Column {
              width: parent.width - chooseButton.width - parent.spacing
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(3)

              Text {
                width: parent.width
                text: root.inputName
                color: root.inputPath === "" ? root.muted : root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                font.bold: root.inputPath !== ""
                elide: Text.ElideMiddle
              }

              Text {
                width: parent.width
                text: root.inputPath === "" ? "WAV, FLAC, MP3, M4A, OGG, or AAC" : root.inputPath
                color: root.muted
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                elide: Text.ElideMiddle
              }
            }

            Button {
              id: chooseButton
              anchors.verticalCenter: parent.verticalCenter
              text: root.inputPath === "" ? "Choose track" : "Change"
              foreground: root.foreground
              enabled: !root.busy
              onClicked: root.chooseFile()
            }
          }
        }

        ButtonGroup {
          width: parent.width
          options: ["Remove selected", "Full separation"]
          value: root.mode === "remove" ? "Remove selected" : "Full separation"
          foreground: root.foreground
          background: root.background
          accent: Color.accent
          fontFamily: root.fontFamily
          onChanged: function(next) {
            root.mode = next === "Full separation" ? "full" : "remove"
            root.outputPath = ""
          }
        }

        Column {
          width: parent.width
          spacing: Style.space(5)

          Text {
            text: "OUTPUT FORMAT"
            color: root.muted
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
            font.letterSpacing: 0.8
          }

          ButtonGroup {
            width: parent.width
            options: ["FLAC", "WAV", "MP4 (AAC)"]
            value: root.outputFormat === "wav" ? "WAV"
              : (root.outputFormat === "mp4" ? "MP4 (AAC)" : "FLAC")
            foreground: root.foreground
            background: root.background
            accent: Color.accent
            fontFamily: root.fontFamily
            enabled: !root.busy
            onChanged: function(next) {
              root.outputFormat = next === "WAV" ? "wav"
                : (next === "MP4 (AAC)" ? "mp4" : "flac")
              root.outputPath = ""
            }
          }

          Text {
            width: parent.width
            text: root.outputFormat === "mp4"
              ? "AAC in an MP4 container · compact and widely playable · lossy"
              : (root.outputFormat === "wav"
                ? "16-bit PCM WAV · widest editor compatibility · lossless"
                : "FLAC · smaller lossless files")
            color: root.muted
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
        }

        Text {
          width: parent.width
          text: root.mode === "full"
            ? "Split the song into vocals, drums, bass, and other instruments."
            : "Choose what to remove. Everything else is mixed back together."
          color: root.muted
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Grid {
          width: parent.width
          visible: root.mode === "remove"
          columns: 2
          spacing: Style.space(8)

          QQC.CheckBox {
            width: (parent.width - parent.spacing) / 2
            text: "Vocals"
            checked: root.removeVocals
            enabled: !root.busy
            palette.text: root.foreground
            font.family: root.fontFamily
            onToggled: root.removeVocals = checked
          }
          QQC.CheckBox {
            width: (parent.width - parent.spacing) / 2
            text: "Drums"
            checked: root.removeDrums
            enabled: !root.busy
            palette.text: root.foreground
            font.family: root.fontFamily
            onToggled: root.removeDrums = checked
          }
          QQC.CheckBox {
            width: (parent.width - parent.spacing) / 2
            text: "Bass"
            checked: root.removeBass
            enabled: !root.busy
            palette.text: root.foreground
            font.family: root.fontFamily
            onToggled: root.removeBass = checked
          }
          QQC.CheckBox {
            width: (parent.width - parent.spacing) / 2
            text: "Other instruments"
            checked: root.removeOther
            enabled: !root.busy
            palette.text: root.foreground
            font.family: root.fontFamily
            onToggled: root.removeOther = checked
          }
        }

        Text {
          width: parent.width
          visible: root.mode === "remove" && !root.selectionValid
          text: root.selectedCount === 0
            ? "Select at least one part to remove."
            : "Keep at least one part in the cleaned mix."
          color: Color.urgent
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          horizontalAlignment: Text.AlignHCenter
        }

        Rectangle {
          width: parent.width
          height: Style.space(6)
          radius: height / 2
          color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.10)
          visible: root.busy || root.progress > 0

          Rectangle {
            width: parent.width * (root.progress / 100)
            height: parent.height
            radius: parent.radius
            color: root.status === "error" ? Color.urgent : Color.accent
          }
        }

        Text {
          width: parent.width
          text: root.statusMessage
          color: root.status === "error" || root.status === "missing" ? Color.urgent : root.muted
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
          horizontalAlignment: Text.AlignHCenter
        }

        Text {
          width: parent.width
          visible: root.outputPath !== ""
          text: root.outputPath
          color: root.muted
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideMiddle
          horizontalAlignment: Text.AlignHCenter
        }

        PanelSeparator { foreground: root.foreground }

        Row {
          width: parent.width
          spacing: Style.space(8)

          Button {
            visible: !root.engineReady && !root.busy
            text: "Set up engine"
            foreground: root.foreground
            onClicked: root.startSetup()
          }

          Button {
            visible: root.engineReady && !root.busy
            text: root.mode === "full" ? "Split into 4 stems" : "Create cleaned mix"
            foreground: root.foreground
            enabled: root.inputPath !== "" && root.selectionValid
            onClicked: root.startProcessing()
          }

          Button {
            visible: root.busy
            text: "Cancel"
            foreground: Color.urgent
            onClicked: root.cancelProcessing()
          }

          Item { width: Math.max(0, parent.width - parent.children[0].width - parent.children[1].width - parent.children[2].width - openButton.width - parent.spacing * 4); height: 1 }

          Button {
            id: openButton
            visible: root.outputPath !== "" && !root.busy
            text: "Open folder"
            foreground: root.foreground
            onClicked: root.openOutput()
          }
        }

        Text {
          width: parent.width
          text: "Output: ~/Desktop/stems/<track>/ · First use downloads the selected model."
          color: root.muted
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          horizontalAlignment: Text.AlignHCenter
          wrapMode: Text.WordWrap
        }
      }
    }
  }
}
