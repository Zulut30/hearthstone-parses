(function() {
  'use strict';

  var activeScatterAnimations = new Map();

  document.addEventListener('DOMContentLoaded', function() {
    var containers = document.querySelectorAll('.hs-meta-scatter-wrapper');
    containers.forEach(function(wrapper, index) {
      initScatterPlot(wrapper, index);
    });
  });

  function initScatterPlot(wrapper, wrapperIndex) {
    var canvas = wrapper.querySelector('.hs-meta-scatter-canvas');
    var hoverInfo = wrapper.querySelector('.hs-meta-scatter-tooltip');
    var rankSelector = wrapper.querySelector('.hs-meta-scatter-rank-selector');
    if (!canvas || !hoverInfo) return;

    var ctx = canvas.getContext('2d');
    var apiUrl = wrapper.getAttribute('data-api-url') || 'https://api.hs-manacost.ru';
    var format = wrapper.getAttribute('data-format') || 'standard'; // standard or wild
    var currentRank = wrapper.getAttribute('data-start-rank') || 'diamond_4to1'; // legend, diamond_4to1, top_5k, top_legend
    var showSelector = wrapper.getAttribute('data-show-selector') === 'yes';

    var RANK_LABELS = {
      'legend': 'Легенда (Legend)',
      'diamond_4to1': 'Алмаз 4-1 (Diamond)',
      'top_5k': 'Топ-5к Легенды (Top 5k)',
      'top_legend': 'Топ-1к Легенды (Top 1k)'
    };

    var AVAILABLE_RANKS = ['top_legend', 'top_5k', 'legend', 'diamond_4to1'];

    // Render rank selector if enabled
    if (showSelector && rankSelector) {
      rankSelector.innerHTML = '';
      AVAILABLE_RANKS.forEach(function(rank) {
        var btn = document.createElement('button');
        btn.className = 'hs-vs-tab-btn rank-tab-btn ' + (rank === currentRank ? 'active' : '');
        btn.textContent = RANK_LABELS[rank] || rank;
        
        btn.addEventListener('click', function() {
          rankSelector.querySelectorAll('.rank-tab-btn').forEach(function(b) { b.classList.remove('active'); });
          btn.classList.add('active');
          currentRank = rank;
          loadScatterData(currentRank);
        });

        rankSelector.appendChild(btn);
      });
    }

    function loadScatterData(rank) {
      hoverInfo.textContent = 'Загрузка данных графика...';
      
      var sourceId = 'hsguru_meta_' + format + '_' + rank;

      fetch(apiUrl + '/datasets/' + sourceId)
        .then(function(res) {
          if (!res.ok) throw new Error('Ошибка HTTP: ' + res.status);
          return res.json();
        })
        .then(function(payload) {
          if (!payload || !payload.data || !payload.data.structured || !payload.data.structured.strategies) {
            throw new Error('Некорректная структура данных');
          }
          var strategies = payload.data.structured.strategies;
          renderScatterPlot(canvas, hoverInfo, ctx, strategies, wrapperIndex);
        })
        .catch(function(err) {
          hoverInfo.innerHTML = '<span style="color: #ff3b30;">Ошибка загрузки графика (' + escapeHtml(sourceId) + '): ' + escapeHtml(err.message) + '</span>';
        });
    }

    // Initial load
    loadScatterData(currentRank);
  }

  function renderScatterPlot(canvas, hoverInfo, ctx, strategies, wrapperIndex) {
    var parsedPoints = strategies.map(function(s) {
      var name = s.Archetype || s.strategy || s.name || '';
      var winrateStr = s['Winrate↓'] || s.Winrate || s.winrate || '0';
      var popularityStr = s.Popularity || s.popularity || '0%';
      
      var winrate = parseFloat(winrateStr) || 0;
      
      var popularity = 0;
      var popMatch = popularityStr.match(/^([\d.,]+)/);
      if (popMatch) {
        popularity = parseFloat(popMatch[1].replace(',', '.')) || 0;
      }
      
      var hsClass = 'Neutral';
      var nameLower = name.toLowerCase();
      if (nameLower.indexOf('dh') !== -1 || nameLower.indexOf('demon hunter') !== -1 || nameLower.indexOf('demonhunter') !== -1) {
        hsClass = 'Demon Hunter';
      } else if (nameLower.indexOf('dk') !== -1 || nameLower.indexOf('death knight') !== -1 || nameLower.indexOf('deathknight') !== -1) {
        hsClass = 'Death Knight';
      } else if (nameLower.indexOf('druid') !== -1) {
        hsClass = 'Druid';
      } else if (nameLower.indexOf('hunter') !== -1) {
        hsClass = 'Hunter';
      } else if (nameLower.indexOf('mage') !== -1) {
        hsClass = 'Mage';
      } else if (nameLower.indexOf('paladin') !== -1 || nameLower.indexOf('turnadin') !== -1) {
        hsClass = 'Paladin';
      } else if (nameLower.indexOf('priest') !== -1) {
        hsClass = 'Priest';
      } else if (nameLower.indexOf('rogue') !== -1) {
        hsClass = 'Rogue';
      } else if (nameLower.indexOf('shaman') !== -1) {
        hsClass = 'Shaman';
      } else if (nameLower.indexOf('warlock') !== -1 || nameLower.indexOf('egglock') !== -1 || nameLower.indexOf('rafaamlock') !== -1) {
        hsClass = 'Warlock';
      } else if (nameLower.indexOf('warrior') !== -1) {
        hsClass = 'Warrior';
      }
      
      return {
        name: name,
        winrate: winrate,
        popularity: popularity,
        popularityStr: popularityStr,
        turns: s.Turns || s.turns || '',
        duration: s.Duration || s.duration || '',
        climbingSpeed: s['Climbing Speed'] || s.climbing_speed || '',
        hsClass: hsClass
      };
    }).filter(function(p) {
      return p.winrate > 0 && p.name;
    });

    var CLASS_COLORS = {
      'Death Knight': '#008f7d',
      'Demon Hunter': '#a330c9',
      'Druid': '#ff7d0a',
      'Hunter': '#abd473',
      'Mage': '#40c7eb',
      'Paladin': '#f58cba',
      'Priest': '#ffffff',
      'Rogue': '#fff569',
      'Shaman': '#0070de',
      'Warlock': '#8787ed',
      'Warrior': '#c79c6e',
      'Neutral': '#999999'
    };

    var width = canvas.width;
    var height = canvas.height;
    var paddingLeft = 60;
    var paddingRight = 40;
    var paddingTop = 30;
    var paddingBottom = 50;

    var chartWidth = width - paddingLeft - paddingRight;
    var chartHeight = height - paddingTop - paddingBottom;

    var xMin = 35;
    var xMax = 65;
    var yMin = 0;
    var maxPop = Math.max.apply(Math, parsedPoints.map(function(p) { return p.popularity; }).concat([5]));
    var yMax = Math.ceil(maxPop / 5) * 5;

    function mapX(wr) {
      return paddingLeft + ((wr - xMin) / (xMax - xMin)) * chartWidth;
    }
    function mapY(pop) {
      return height - paddingBottom - ((pop - yMin) / (yMax - yMin)) * chartHeight;
    }

    var hoveredPoint = null;

    function draw() {
      // Clear with background color matching the theme beautifully
      ctx.fillStyle = '#1e1e24';
      ctx.fillRect(0, 0, width, height);

      ctx.strokeStyle = '#2d2d38';
      ctx.lineWidth = 1;
      ctx.fillStyle = '#a0a0b0';
      ctx.font = '11px sans-serif';
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';

      // Horizontal Gridlines
      var yStep = yMax <= 10 ? 2 : 5;
      for (var pop = yMin; pop <= yMax; pop += yStep) {
        var y = mapY(pop);
        ctx.beginPath();
        ctx.moveTo(paddingLeft, y);
        ctx.lineTo(width - paddingRight, y);
        ctx.stroke();
        ctx.fillText(pop + '%', paddingLeft - 8, y);
      }

      // Vertical Gridlines
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      for (var wr = xMin; wr <= xMax; wr += 5) {
        var x = mapX(wr);
        ctx.beginPath();
        ctx.moveTo(x, paddingTop);
        ctx.lineTo(x, height - paddingBottom);
        ctx.stroke();
        ctx.fillText(wr + '%', x, height - paddingBottom + 8);
      }

      // Solid Axes
      ctx.strokeStyle = '#4e4e5a';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(paddingLeft, paddingTop);
      ctx.lineTo(paddingLeft, height - paddingBottom);
      ctx.lineTo(width - paddingRight, height - paddingBottom);
      ctx.stroke();

      // Axis Titles
      ctx.fillStyle = '#d0d0e0';
      ctx.font = 'bold 12px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Винрейт (Winrate)', paddingLeft + chartWidth / 2, height - paddingBottom + 28);

      ctx.save();
      ctx.translate(15, paddingTop + chartHeight / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText('Популярность (Popularity)', 0, 0);
      ctx.restore();

      parsedPoints.forEach(function(p) {
        if (p !== hoveredPoint) drawPoint(p, false);
      });

      if (hoveredPoint) {
        drawPoint(hoveredPoint, true);
      }
    }

    function drawPoint(p, isHovered) {
      var cx = mapX(p.winrate);
      var cy = mapY(p.popularity);
      var color = CLASS_COLORS[p.hsClass] || CLASS_COLORS['Neutral'];

      if (isHovered) {
        ctx.beginPath();
        ctx.arc(cx, cy, 10, 0, 2 * Math.PI);
        ctx.fillStyle = 'rgba(255, 255, 255, 0.25)';
        ctx.fill();
      }

      ctx.beginPath();
      ctx.arc(cx, cy, isHovered ? 7 : 5, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = isHovered ? '#fff' : 'rgba(0, 0, 0, 0.5)';
      ctx.lineWidth = isHovered ? 2 : 1;
      ctx.stroke();

      ctx.font = isHovered ? 'bold 12px sans-serif' : '10px sans-serif';
      ctx.fillStyle = isHovered ? '#fff' : '#cccccc';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';

      ctx.shadowColor = 'rgba(0, 0, 0, 0.95)';
      ctx.shadowBlur = isHovered ? 6 : 4;
      ctx.shadowOffsetX = 1;
      ctx.shadowOffsetY = 1;

      ctx.fillText(p.name, cx + 8, cy);

      ctx.shadowColor = 'transparent';
      ctx.shadowBlur = 0;
      ctx.shadowOffsetX = 0;
      ctx.shadowOffsetY = 0;
    }

    // Capture previous mousemove handler by replacing canvas element with its clone to clear listeners
    var newCanvas = canvas.cloneNode(true);
    canvas.parentNode.replaceChild(newCanvas, canvas);
    canvas = newCanvas;

    canvas.addEventListener('mousemove', function(e) {
      var rect = canvas.getBoundingClientRect();
      var mouseX = (e.clientX - rect.left) * (width / rect.width);
      var mouseY = (e.clientY - rect.top) * (height / rect.height);

      var found = null;
      var minDistance = 15;

      for (var i = 0; i < parsedPoints.length; i++) {
        var p = parsedPoints[i];
        var cx = mapX(p.winrate);
        var cy = mapY(p.popularity);
        var dist = Math.hypot(mouseX - cx, mouseY - cy);
        if (dist < minDistance) {
          minDistance = dist;
          found = p;
        }
      }

      if (found !== hoveredPoint) {
        hoveredPoint = found;
        canvas.style.cursor = hoveredPoint ? 'pointer' : 'default';
        
        if (hoveredPoint) {
          hoverInfo.innerHTML = 
            '<span style="color: ' + CLASS_COLORS[hoveredPoint.hsClass] + '; font-weight: bold;">' + escapeHtml(hoveredPoint.name) + ' (' + escapeHtml(hoveredPoint.hsClass) + ')</span> · ' +
            'Винрейт: <strong style="color: #4cd137">' + hoveredPoint.winrate + '%</strong> · ' +
            'Популярность: <strong style="color: #00a8ff">' + escapeHtml(hoveredPoint.popularityStr) + '</strong>' +
            (hoveredPoint.turns ? ' · Ходов: <strong>' + escapeHtml(hoveredPoint.turns) + '</strong>' : '') +
            (hoveredPoint.climbingSpeed ? ' · Скорость: <strong>' + escapeHtml(hoveredPoint.climbingSpeed) + '</strong>' : '');
        } else {
          hoverInfo.textContent = 'Наведите на точку, чтобы увидеть детали';
        }
        draw();
      }
    });

    canvas.addEventListener('mouseleave', function() {
      if (hoveredPoint) {
        hoveredPoint = null;
        hoverInfo.textContent = 'Наведите на точку, чтобы увидеть детали';
        canvas.style.cursor = 'default';
        draw();
      }
    });

    hoverInfo.textContent = 'Наведите на точку, чтобы увидеть детали';
    draw();
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

})();
