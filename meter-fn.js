    async function meterCapture() {
      var btn = document.getElementById("btnMeterCapture");
      var placeholder = document.getElementById("meterPlaceholder");
      var overlay = document.getElementById("meterOverlay");
      var bar = document.getElementById("meterBar");
      var labelBg = document.getElementById("meterLabelBg");
      var labelFg = document.getElementById("meterLabelFg");
      if (btn) btn.disabled = true;
      var mn = document.getElementById("meterMin").value || 0;
      var mx = document.getElementById("meterMax").value || 6;
      var dv = document.getElementById("meterDivs").value || 29;
      var term = document.getElementById("meterTerminal");
      meterCapturing = true;

      if (overlay) overlay.style.display = "block";
      if (bar) bar.style.width = "0%";
      if (labelFg) labelFg.style.clipPath = "inset(0 100% 0 0)";
      var cur = "拍摄照片";
      if (labelBg) labelBg.textContent = cur;
      if (labelFg) labelFg.textContent = cur;
      if (placeholder) { placeholder.textContent = "读数中"; placeholder.style.display = "flex"; }
      document.getElementById("btnMeterPlay").disabled = true;
      document.getElementById("btnMeterStop").disabled = true;
      document.getElementById("btnMeterCapture").disabled = true;
      if (term) term.innerHTML = '';
      showToast("正在进行仪表读数...");

      var steps = [
        {pct:10, label:"加载模型", text:'<p class="log-sys">ONNX models loaded OK</p>'},
        {pct:22, label:"目标检测", text:'<p class="log-sys">[1/6] Detecting meter...</p><p class="log-sys">Meter bbox: (--, --, --, --), conf=--</p>'},
        {pct:34, label:"参数加载", text:'<p class="log-sys">[2/6] Using manual range params</p>'},
        {pct:48, label:"语义分割", text:'<p class="log-sys">[3/6] Segmenting (range '+mn+'~'+mx+', '+dv+' divs)...</p>'},
        {pct:64, label:"极坐标变换", text:'<p class="log-sys">[4/6] Erosion...</p><p class="log-sys">[5/6] Polar transform...</p>'},
        {pct:80, label:"计算读数", text:'<p class="log-sys">[6/6] Calculating reading...</p><p class="log-sys">Raw scales: --, Pointer: [--]</p><p class="log-sys">Fixed scales: --</p>'}
      ];
      var step = 0;
      var termTimer = setInterval(function() {
        if (step < steps.length) {
          if (term) { term.innerHTML = steps[step].text; term.scrollTop = term.scrollHeight; }
          var pct = steps[step].pct;
          if (bar) bar.style.width = pct + "%";
          if (labelFg) labelFg.style.clipPath = "inset(0 " + (100 - pct) + "% 0 0)";
          var lbl = steps[step].label;
          if (labelBg) labelBg.textContent = lbl;
          if (labelFg) labelFg.textContent = lbl;
          step++;
        }
      }, 1800);

      try {
        var now = new Date();
        var clientTime = now.getFullYear() + "-" +
          String(now.getMonth()+1).padStart(2,'0') + "-" + String(now.getDate()).padStart(2,'0') + " " +
          String(now.getHours()).padStart(2,'0') + ":" + String(now.getMinutes()).padStart(2,'0') + ":" +
          String(now.getSeconds()).padStart(2,'0');
        var r1 = await fetch("/meter-read.php?action=capture&min=" + mn + "&max=" + mx + "&divisions=" + dv + "&time=" + encodeURIComponent(clientTime));
        var d1 = await r1.json();
        if (!d1.ok) {
          clearInterval(termTimer);
          if (overlay) overlay.style.display = "none"; if (bar) bar.style.width = "0%";
          if (placeholder) placeholder.style.display = "none";
          showToast("读数失败: " + (d1.error || "unknown"));
          if (btn) btn.disabled = false; meterCapturing = false; return;
        }
        var done = false;
        var poll = setInterval(async function() {
          if (done) return;
          try {
            var r2 = await fetch("/meter-read.php?action=poll&id=" + d1.id);
            var d2 = await r2.json();
            if (d2.status === "done") {
              done = true;
              clearInterval(poll); clearInterval(termTimer);
              if (bar) bar.style.width = "100%";
              if (labelFg) labelFg.style.clipPath = "inset(0 0 0 0)";
              var fin = "读数完成";
              if (labelBg) labelBg.textContent = fin;
              if (labelFg) labelFg.textContent = fin;
              if (d2.log && term) { term.innerHTML = d2.log.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/\n/g,"<br>"); term.scrollTop = term.scrollHeight; }
              meterCapturing = false;
              if (d2.reading !== null) {
                document.getElementById("meterReading").textContent = d2.reading;
                document.getElementById("meterTime").textContent = d2.time;
                showToast("读数完成: " + d2.reading);
              } else { showToast("读数失败: 未能识别"); }
              setTimeout(function() {
                if (overlay) overlay.style.display = "none"; if (bar) bar.style.width = "0%";
                if (placeholder) placeholder.style.display = "none";
              }, 1500);
              if (btn) btn.disabled = false; loadMeterHistory(); startMeterPoll();
            }
          } catch(ex) { if (!done) { clearInterval(poll); clearInterval(termTimer); if (overlay) overlay.style.display = "none"; meterCapturing = false; } }
        }, 800);
      } catch(e) {
        clearInterval(termTimer);
        if (overlay) overlay.style.display = "none"; if (bar) bar.style.width = "0%";
        if (placeholder) placeholder.style.display = "none";
        showToast("读数失败: 无法连接服务");
        if (btn) btn.disabled = false; meterCapturing = false;
      }
    }

