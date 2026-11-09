/* Summoner's Rift drawings: event maps (kills / assists / deaths) and heatmaps.
   The map picture comes from Data Dragon; drawings sit on top of it so the
   canvas never touches a cross-origin image. */
(function () {
  const S = 14870;
  const toPx = (x, y, W) => [((x + 120) / 14990) * W, W - ((y + 120) / 15100) * W];
  const mirror = (x, y, team) => (team === 200 ? [S - y, S - x] : [x, y]);

  function frame(version, inner) {
    const fig = document.createElement("figure");
    fig.style.position = "relative";
    fig.innerHTML = `<img src="https://ddragon.leagueoflegends.com/cdn/${version}/img/map/map11.png" alt="" style="width:100%;display:block;border-radius:4px;filter:saturate(.55) brightness(.8)">`;
    inner.style.position = "absolute";
    inner.style.inset = "0";
    inner.style.width = "100%";
    inner.style.height = "100%";
    fig.appendChild(inner);
    return fig;
  }

  // events: [t, x, y, kind('k'|'a'|'d'), team]
  function eventMap(version, events, opts = {}) {
    const W = 512;
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${W}`);
    svg.style.background = "transparent";
    const order = { a: 0, k: 1, d: 2 };
    [...events].sort((a, b) => order[a[3]] - order[b[3]]).forEach((ev) => {
      let [t, x, y, kind, team] = ev;
      if (opts.mirror) [x, y] = mirror(x, y, team);
      const [px, py] = toPx(x, y, W);
      if (kind === "k") {
        const c = document.createElementNS(ns, "circle");
        c.setAttribute("cx", px); c.setAttribute("cy", py); c.setAttribute("r", 5.5);
        c.setAttribute("fill", "#3fbf6e"); c.setAttribute("stroke", "#0b0f10"); c.setAttribute("stroke-width", 1);
        svg.appendChild(c);
      } else if (kind === "a") {
        const c = document.createElementNS(ns, "circle");
        c.setAttribute("cx", px); c.setAttribute("cy", py); c.setAttribute("r", 5);
        c.setAttribute("fill", "none"); c.setAttribute("stroke", "#8cc0ff"); c.setAttribute("stroke-width", 1.6);
        svg.appendChild(c);
      } else {
        const g = document.createElementNS(ns, "path");
        const s = 5;
        g.setAttribute("d", `M${px - s} ${py - s}L${px + s} ${py + s}M${px + s} ${py - s}L${px - s} ${py + s}`);
        g.setAttribute("stroke", "#ff5a4e"); g.setAttribute("stroke-width", 2.6); g.setAttribute("stroke-linecap", "round");
        svg.appendChild(g);
      }
    });
    return frame(version, svg);
  }

  // points: [x, y, team]
  function heatMap(version, points, opts = {}) {
    const W = 256;
    const canvas = document.createElement("canvas");
    canvas.width = W; canvas.height = W;
    const ctx = canvas.getContext("2d");
    const radius = opts.radius || 13;
    ctx.globalCompositeOperation = "lighter";
    const alpha = Math.max(0.04, Math.min(0.35, 18 / Math.max(points.length, 1)));
    points.forEach(([x0, y0, team]) => {
      const [x, y] = opts.mirror === false ? [x0, y0] : mirror(x0, y0, team);
      const [px, py] = toPx(x, y, W);
      const g = ctx.createRadialGradient(px, py, 0, px, py, radius);
      g.addColorStop(0, `rgba(0,0,0,${alpha})`);
      g.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g;
      ctx.fillRect(px - radius, py - radius, radius * 2, radius * 2);
    });
    const img = ctx.getImageData(0, 0, W, W);
    const d = img.data;
    let max = 0;
    for (let i = 3; i < d.length; i += 4) max = Math.max(max, d[i]);
    const ramp = [[30, 90, 255], [0, 200, 255], [255, 230, 0], [255, 90, 0], [230, 0, 0]];
    for (let i = 0; i < d.length; i += 4) {
      const v = max ? d[i + 3] / max : 0;
      if (v < 0.04) { d[i + 3] = 0; continue; }
      const pos = Math.min(v, 0.999) * (ramp.length - 1);
      const k = Math.floor(pos), f = pos - k;
      const a = ramp[k], b = ramp[k + 1];
      d[i] = a[0] + (b[0] - a[0]) * f;
      d[i + 1] = a[1] + (b[1] - a[1]) * f;
      d[i + 2] = a[2] + (b[2] - a[2]) * f;
      d[i + 3] = Math.min(235, 60 + v * 220);
    }
    ctx.globalCompositeOperation = "copy";
    ctx.putImageData(img, 0, 0);
    canvas.style.background = "transparent";
    return frame(version, canvas);
  }

  window.RiftMaps = { eventMap, heatMap };
})();
