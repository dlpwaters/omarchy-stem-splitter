import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui

BarWidget {
  id: root
  moduleName: "io.github.dlpwaters.stem-splitter"

  readonly property bool opened: panelLoader.item
    ? panelLoader.item.opened === true
    : false
  readonly property bool busy: panelLoader.item
    ? panelLoader.item.busy === true
    : false
  readonly property bool popoutSwitchClosing: panelLoader.item
    ? panelLoader.item.popoutSwitchClosing === true
    : false

  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function toggle() { if (panelLoader.item) panelLoader.item.toggle() }
  function closeForPopoutSwitch() {
    if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
  }
  function processFile(path, mode, targets) {
    if (panelLoader.item) panelLoader.item.processFile(path, mode, targets)
  }
  function processFileAs(path, mode, targets, format) {
    if (panelLoader.item) panelLoader.item.processFileAs(path, mode, targets, format)
  }

  function injectPanel() {
    if (!panelLoader.item) return
    panelLoader.item.bar = root.bar
    panelLoader.item.anchorItem = button
    panelLoader.item.hostWidget = root
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  IpcHandler {
    target: "io.github.dlpwaters.stem-splitter"
    function open() { root.open() }
    function close() { root.close() }
    function show() { root.open() }
    function hide() { root.close() }
    function toggle() { root.toggle() }
    function process(path: string, mode: string, targets: string) {
      root.processFile(path, mode, targets)
    }
    function processAs(path: string, mode: string, targets: string, format: string) {
      root.processFileAs(path, mode, targets, format)
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.busy ? "󰦖" : "󰝚"
    tooltipText: root.busy ? "Stem Splitter · Processing" : "Stem Splitter"
    onPressed: function(mouseButton) {
      if (mouseButton !== Qt.RightButton) root.toggle()
    }
  }
}
