import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Omarchy Without Borders — ícone na barra + painel com máquinas e ações.
// Ícone: apagado = daemon parado/sem conexões · normal = N máquinas · acento = controlando outra máquina.
Panel {
  id: root
  moduleName: "br.andrebruno.owb"
  ipcTarget: "br.andrebruno.owb"
  manageIpc: false

  property bool daemonUp: false
  property var peers: []            // [{name, addr, client}] deduplicado por nome
  property string controlling: ""
  property var edges: []
  property string machineName: ""
  property var matrix: []
  property bool clipboardOn: true
  property int uptime: 0
  property bool busy: false

  // i18n: pt-BR if LANG/LC_ALL start with "pt", else English
  readonly property bool pt: {
    var l = String(Quickshell.env("LC_ALL") || Quickshell.env("LC_MESSAGES") || Quickshell.env("LANG") || "")
    return l.toLowerCase().indexOf("pt") === 0
  }
  function tr(en, ptbr) { return pt ? ptbr : en }

  readonly property int refreshSec: {
    var n = parseInt(String(settings && settings.refreshIntervalSec !== undefined ? settings.refreshIntervalSec : 5), 10)
    return isFinite(n) && n >= 2 ? n : 5
  }
  readonly property color fg: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(fg, 1.55)
  readonly property color iconColor: !daemonUp || peers.length === 0 ? Qt.darker(barForeground, 1.7)
    : (controlling !== "" ? Color.accent : barForeground)
  readonly property string statusLine: !daemonUp ? tr("DAEMON STOPPED", "DAEMON PARADO")
    : controlling !== "" ? tr("CONTROLLING ", "CONTROLANDO ") + controlling.toUpperCase()
    : peers.length === 0 ? tr("NO MACHINES CONNECTED", "SEM MÁQUINAS CONECTADAS")
    : peers.length + (peers.length === 1 ? tr(" MACHINE CONNECTED", " MÁQUINA CONECTADA") : tr(" MACHINES CONNECTED", " MÁQUINAS CONECTADAS"))
  readonly property string tooltip: !daemonUp ? tr("Omarchy Without Borders: daemon stopped (owb enable)", "Omarchy Without Borders: daemon parado (owb enable)")
    : controlling !== "" ? tr("Controlling ", "Controlando ") + controlling + tr(" — move the mouse back across the edge", " — mova o mouse de volta pela borda")
    : peers.length === 0 ? tr("Omarchy Without Borders: no machines connected", "Omarchy Without Borders: sem máquinas conectadas")
    : peers.map(function(p) { return p.name }).join(", ") + (edges.length ? tr(" · edges: ", " · bordas: ") + edges.join(", ") : "")

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function refresh() { if (!statusProc.running) statusProc.running = true }

  function run(cmd) {
    if (!bar) return
    busy = true
    bar.run(cmd)
    busyTimer.restart()
  }

  IpcHandler {
    target: "br.andrebruno.owb"
    function open() { root.open() }
    function close() { root.close() }
    function toggle() { root.toggle() }
    function refresh() { root.refresh() }
  }

  onOpenedChanged: if (opened) refresh()

  Process {
    id: statusProc
    command: ["sh", "-c", "printf 'status\\n' | timeout 3 python3 -c 'import socket,sys,os;s=socket.socket(socket.AF_UNIX);s.connect(os.path.join(os.environ.get(\"XDG_RUNTIME_DIR\",\"/tmp\"),\"owb.sock\"));s.sendall(sys.stdin.buffer.read());print(s.recv(65536).decode())'"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var st
        try { st = JSON.parse(text) } catch (e) { root.daemonUp = false; root.peers = []; root.controlling = ""; return }
        root.daemonUp = true
        var seen = {}, list = []
        for (var i = 0; i < st.peers.length; i++) {
          var p = st.peers[i]
          if (!p.trusted || seen[p.name]) continue
          seen[p.name] = true
          list.push({ name: p.name, addr: p.addr, client: p.client })
        }
        root.peers = list
        root.controlling = st.controlling || ""
        root.edges = st.edges || []
        root.machineName = st.machine_name || ""
        root.matrix = st.matrix || []
        root.clipboardOn = !!st.clipboard
        root.uptime = st.uptime_s || 0
      }
    }
    onExited: function(code) { if (code !== 0) { root.daemonUp = false; root.peers = []; root.controlling = "" } }
  }

  Timer { interval: root.refreshSec * 1000; running: true; repeat: true; triggeredOnStart: true; onTriggered: root.refresh() }
  Timer { interval: 1500; running: root.opened; repeat: true; onTriggered: root.refresh() }
  Timer { id: busyTimer; interval: 4000; onTriggered: { root.busy = false; root.refresh() } }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    foreground: root.iconColor
    slotSize: Style.bar.statusSlot
    fontSize: Style.font.caption
    tooltipText: root.opened ? "" : root.tooltip
    onPressed: function(b) {
      if (b === Qt.RightButton) root.run("owb release")
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(360))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: Style.space(12)

        // ---------- cabeçalho ----------
        Item {
          width: parent.width
          implicitHeight: Math.max(heroIcon.implicitHeight, heroLabels.implicitHeight)

          Text {
            id: heroIcon
            text: ""
            color: root.iconColor
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.display
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
          }

          Column {
            id: heroLabels
            anchors.left: heroIcon.right
            anchors.leftMargin: Style.space(14)
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            Text {
              text: "Omarchy Without Borders"
              color: root.fg
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
              elide: Text.ElideRight
              width: parent.width
            }
            Text {
              text: root.statusLine
              color: root.controlling !== "" ? Color.accent : root.dim
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
              font.letterSpacing: 1.2
              elide: Text.ElideRight
              width: parent.width
            }
          }
        }

        PanelSeparator { width: parent.width; foreground: root.fg }

        // ---------- máquinas ----------
        PanelSectionHeader { text: root.tr("MACHINES", "MÁQUINAS"); foreground: root.fg; fontFamily: root.bar.fontFamily }

        Column {
          width: parent.width
          spacing: Style.space(4)

          Text {
            visible: root.peers.length === 0
            text: root.daemonUp ? root.tr("None connected. On Windows: same key and this machine (" + root.machineName + ") in the matrix.", "Nenhuma conectada. No Windows: mesma chave e esta máquina (" + root.machineName + ") no matrix.") : root.tr("Start the service: owb enable", "Inicie o serviço: owb enable")
            color: root.dim
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.body
            wrapMode: Text.WordWrap
            width: parent.width
          }

          Repeater {
            model: root.peers
            delegate: Item {
              width: column.width
              implicitHeight: Style.space(24)
              Text {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                text: (root.controlling === modelData.name ? "  " : "  ") + modelData.name
                color: root.controlling === modelData.name ? Color.accent : root.fg
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.body
              }
              Text {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                text: modelData.addr
                color: root.dim
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                elide: Text.ElideMiddle
                width: parent.width * 0.5
                horizontalAlignment: Text.AlignRight
              }
            }
          }
        }

        // ---------- matrix ----------
        Text {
          visible: root.matrix.length > 0
          text: "Matrix: " + root.matrix.filter(function(n) { return n }).map(function(n) { return n.toUpperCase() === root.machineName.toUpperCase() ? "[" + n + "]" : n }).join("  ·  ")
          color: root.dim
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
          width: parent.width
        }
        Text {
          text: root.tr("Active edges: ", "Bordas ativas: ") + (root.edges.length ? root.edges.join(", ") : root.tr("none", "nenhuma")) + "   ·   Clipboard: " + (root.clipboardOn ? "on" : "off")
          color: root.dim
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
          width: parent.width
        }

        PanelSeparator { width: parent.width; foreground: root.fg }

        // ---------- ações ----------
        Row {
          width: parent.width
          spacing: Style.space(8)

          Button {
            text: root.tr("Reconnect", "Reconectar"); iconText: ""
            tooltipText: root.tr("Restart the service (owb restart)", "Reinicia o serviço (owb restart)")
            foreground: root.fg; fontFamily: root.bar.fontFamily
            enabled: !root.busy
            onClicked: root.run("owb restart")
          }
          Button {
            text: root.tr("Release cursor", "Devolver cursor"); iconText: ""
            tooltipText: root.tr("Leave remote-control mode (owb release)", "Sai do modo de controle remoto (owb release)")
            foreground: root.fg; fontFamily: root.bar.fontFamily
            enabled: root.controlling !== ""
            onClicked: root.run("owb release")
          }
        }
        Row {
          width: parent.width
          spacing: Style.space(8)

          Button {
            text: root.tr("Configure", "Configurar"); iconText: ""
            tooltipText: root.tr("owb setup wizard", "Assistente owb setup")
            foreground: root.fg; fontFamily: root.bar.fontFamily
            onClicked: { root.close(); root.run("omarchy-launch-floating-terminal-with-presentation 'owb setup'") }
          }
          Button {
            text: "Logs"; iconText: ""
            tooltipText: "owb logs -f"
            foreground: root.fg; fontFamily: root.bar.fontFamily
            onClicked: { root.close(); root.run("omarchy-launch-floating-terminal-with-presentation 'owb logs -f'") }
          }
          Button {
            text: "Status"; iconText: ""
            tooltipText: root.tr("owb status in a terminal", "owb status em um terminal")
            foreground: root.fg; fontFamily: root.bar.fontFamily
            onClicked: { root.close(); root.run("omarchy-launch-floating-terminal-with-presentation 'owb status; echo; read -p \"Enter\"'") }
          }
        }
      }
    }
  }
}
