import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Ícone na barra: cinza = daemon parado/sem conexões, normal = N máquinas, acento = controlando outra máquina.
BarWidget {
  id: root
  moduleName: "br.andrebruno.owb"

  property bool daemonUp: false
  property int peerCount: 0
  property var peerNames: []
  property string controlling: ""
  property string edges: ""
  property string machineName: ""

  readonly property int refreshSec: {
    var n = parseInt(String(settings && settings.refreshIntervalSec !== undefined ? settings.refreshIntervalSec : 5), 10)
    return isFinite(n) && n >= 2 ? n : 5
  }
  readonly property color fg: bar ? bar.foreground : Color.foreground
  readonly property color iconColor: !daemonUp || peerCount === 0 ? Qt.darker(fg, 1.7) : (controlling !== "" ? Color.accent : fg)
  readonly property string tooltip: !daemonUp ? "Omarchy Without Borders: daemon parado (owb enable)"
    : peerCount === 0 ? "Omarchy Without Borders: sem máquinas conectadas"
    : (controlling !== "" ? "Controlando " + controlling + " — mova o mouse de volta pela borda"
       : peerCount + " máquina(s): " + peerNames.join(", ") + (edges !== "" ? " · bordas: " + edges : ""))

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function refresh() { if (!statusProc.running) statusProc.running = true }

  Process {
    id: statusProc
    command: ["sh", "-c", "printf 'status\n' | timeout 3 python3 -c 'import socket,sys,os;s=socket.socket(socket.AF_UNIX);s.connect(os.path.join(os.environ.get(\"XDG_RUNTIME_DIR\",\"/tmp\"),\"owb.sock\"));s.sendall(sys.stdin.buffer.read());print(s.recv(65536).decode())'"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var st
        try { st = JSON.parse(text) } catch (e) { root.daemonUp = false; root.peerCount = 0; root.controlling = ""; return }
        root.daemonUp = true
        var names = {}
        for (var i = 0; i < st.peers.length; i++) if (st.peers[i].trusted) names[st.peers[i].name] = true
        root.peerNames = Object.keys(names)
        root.peerCount = root.peerNames.length
        root.controlling = st.controlling || ""
        root.edges = (st.edges || []).join(", ")
        root.machineName = st.machine_name || ""
      }
    }
    onExited: function(code) { if (code !== 0) { root.daemonUp = false; root.peerCount = 0; root.controlling = "" } }
  }

  Timer {
    interval: root.refreshSec * 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""            // monitor (nerd font)
    foreground: root.iconColor
    slotSize: Style.bar.statusSlot
    fontSize: Style.font.caption
    tooltipText: root.tooltip
    onPressed: function(mouseButton) {
      if (!root.bar) return
      if (mouseButton === Qt.RightButton) root.bar.run("owb release")
      else root.bar.run("omarchy-launch-floating-terminal-with-presentation 'owb status; echo; read -p \"Enter para fechar\"'")
    }
  }
}
