(function() {
  'use strict';

  var activeAnimations = new Map();

  document.addEventListener('DOMContentLoaded', function() {
    var containers = document.querySelectorAll('.hs-vs-radar-wrapper');
    containers.forEach(function(wrapper, index) {
      initRadarChart(wrapper, index);
    });
  });

  function initRadarChart(wrapper, wrapperIndex) {
    var canvas = wrapper.querySelector('.hs-vs-radar-canvas');
    var hoverInfo = wrapper.querySelector('.hs-vs-radar-hover-info');
    var classTabs = wrapper.querySelector('.hs-vs-class-tabs');
    var archTabs = wrapper.querySelector('.hs-vs-archetype-tabs');
    var searchInput = wrapper.querySelector('.hs-vs-radar-search');
    var resetBtn = wrapper.querySelector('.hs-vs-radar-reset-btn');
    var nodesTableBody = wrapper.querySelector('.hs-vs-nodes-table tbody');
    var cardTitle = wrapper.querySelector('.hs-vs-selected-card-title');
    var cardDetails = wrapper.querySelector('.hs-vs-selected-card-details');

    if (!canvas) return;

    var ctx = canvas.getContext('2d');
    var apiUrl = wrapper.getAttribute('data-api-url') || 'https://api.hs-manacost.ru';
    var startClass = wrapper.getAttribute('data-start-class') || ''; // e.g., 'Druid'
    var lockClass = wrapper.getAttribute('data-lock-class') === 'yes';

    hoverInfo.textContent = 'Загрузка радаров Vicious Syndicate...';

    fetch(apiUrl + '/datasets/vicious_syndicate_radars')
      .then(function(res) {
        if (!res.ok) throw new Error('Ошибка HTTP: ' + res.status);
        return res.json();
      })
      .then(function(payload) {
        if (!payload || !payload.data || !payload.data.radars) {
          throw new Error('Некорректная структура данных');
        }
        var data = payload.data;
        hoverInfo.textContent = 'Наведите на карту для деталей';
        setupRadarGraph(wrapper, data, canvas, ctx, hoverInfo, classTabs, archTabs, searchInput, resetBtn, nodesTableBody, cardTitle, cardDetails, startClass, lockClass, wrapperIndex);
      })
      .catch(function(err) {
        hoverInfo.innerHTML = '<span style="color: #ff3b30;">Ошибка загрузки радаров: ' + escapeHtml(err.message) + '</span>';
      });
  }

  function setupRadarGraph(wrapper, data, canvas, ctx, hoverInfo, classTabs, archTabs, searchInput, resetBtn, nodesTableBody, cardTitle, cardDetails, startClass, lockClass, wrapperIndex) {
    var currentClass = null;
    var currentArchetype = null;
    var nodes = [];
    var edges = [];
    var draggedNode = null;
    var hoveredNode = null;
    var selectedNode = null;
    var searchText = '';

    var CLASS_TRANSLATIONS = {
      'DeathKnight': 'Рыцарь смерти',
      'DemonHunter': 'Охотник на демонов',
      'Druid': 'Друид',
      'Hunter': 'Охотник',
      'Mage': 'Маг',
      'Paladin': 'Паладин',
      'Priest': 'Жрец',
      'Rogue': 'Разбойник',
      'Shaman': 'Шаман',
      'Warlock': 'Чернокнижник',
      'Warrior': 'Воин'
    };

    var CLASS_COLORS_BORDER = {
      'DeathKnight': '#008f7d', 'DemonHunter': '#a330c9', 'Druid': '#ff7d0a',
      'Hunter': '#abd473', 'Mage': '#40c7eb', 'Paladin': '#f58cba',
      'Priest': '#ffffff', 'Rogue': '#fff569', 'Shaman': '#0070de',
      'Warlock': '#8787ed', 'Warrior': '#c79c6e'
    };

    // Normalize starting class if provided
    if (startClass) {
      // Find matching class matching case-insensitively
      var foundClass = data.classes_summary.find(function(c) {
        return c.class.toLowerCase() === startClass.toLowerCase();
      });
      if (foundClass) {
        currentClass = foundClass.class;
      }
    }

    if (!currentClass && data.classes_summary && data.classes_summary[0]) {
      currentClass = data.classes_summary[0].class;
    }

    if (!currentClass) {
      currentClass = data.radars[0] ? data.radars[0].class : null;
    }

    // Render Class Tabs
    if (classTabs && data.classes_summary) {
      classTabs.innerHTML = '';
      
      if (lockClass) {
        // If locked, hide the main class selector tabs completely
        classTabs.style.display = 'none';
      } else {
        classTabs.style.display = 'flex';
        data.classes_summary.forEach(function(c) {
          var btn = document.createElement('button');
          btn.className = 'hs-vs-tab-btn class-tab-btn ' + (c.class === currentClass ? 'active' : '');
          btn.style.borderColor = CLASS_COLORS_BORDER[c.class] || '#444';
          
          var displayName = CLASS_TRANSLATIONS[c.class] || c.class;
          var badge = '';
          if (c.has_archetypes) {
            badge = ' <span style="background: rgba(255, 159, 28, 0.2); color: #ff9f1c; padding: 1px 4px; border-radius: 4px; font-size: 0.65rem; font-weight: bold; margin-left: 4px;">+арх</span>';
          }
          btn.innerHTML = displayName + badge;
          btn.setAttribute('data-class', c.class);

          btn.addEventListener('click', function() {
            classTabs.querySelectorAll('.class-tab-btn').forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
            currentClass = c.class;
            currentArchetype = null;
            rebuildArchetypeTabs(currentClass);
            loadClassRadar(currentClass, null);
          });

          classTabs.appendChild(btn);
        });
      }
    }

    function rebuildArchetypeTabs(clsName) {
      if (!archTabs) return;
      archTabs.innerHTML = '';

      var classRadars = data.radars.filter(function(r) { return r.class === clsName; });
      
      classRadars.sort(function(a, b) {
        if (a.archetype === null) return -1;
        if (b.archetype === null) return 1;
        return a.archetype.localeCompare(b.archetype);
      });

      // Show archetype tabs only if there are multiple options
      if (classRadars.length > 1) {
        archTabs.style.display = 'flex';
        classRadars.forEach(function(r, i) {
          var btn = document.createElement('button');
          btn.className = 'hs-vs-tab-btn arch-tab-btn ' + (i === 0 ? 'active' : '');
          btn.style.fontSize = '0.8rem';
          btn.style.padding = '0.3rem 0.6rem';
          btn.style.borderRadius = '4px';
          btn.textContent = r.archetype ? r.archetype : 'Общий (Класс)';
          
          btn.addEventListener('click', function() {
            archTabs.querySelectorAll('.arch-tab-btn').forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
            currentArchetype = r.archetype;
            loadClassRadar(currentClass, currentArchetype);
          });

          archTabs.appendChild(btn);
        });
      } else {
        archTabs.style.display = 'none';
      }
    }

    if (searchInput) {
      searchInput.addEventListener('input', function(e) {
        searchText = e.target.value.toLowerCase().trim();
      });
    }

    if (resetBtn) {
      resetBtn.addEventListener('click', function() {
        if (searchInput) searchInput.value = '';
        searchText = '';
        selectedNode = null;
        hoveredNode = null;
        updateSelectedCardView();
        loadClassRadar(currentClass, currentArchetype);
      });
    }

    function loadClassRadar(clsName, archetype) {
      archetype = archetype || null;
      var radar = data.radars.find(function(r) { return r.class === clsName && r.archetype === archetype; });
      if (!radar) return;

      selectedNode = null;
      hoveredNode = null;
      updateSelectedCardView();

      // Show deck code section if available
      var deckSec = wrapper.querySelector('.hs-vs-deck-code-section');
      var deckInp = wrapper.querySelector('.hs-vs-deck-code-input');
      var deckBtn = wrapper.querySelector('.hs-vs-deck-code-copy-btn');
      
      if (deckSec && deckInp && deckBtn) {
        if (radar.deck_code) {
          deckInp.value = radar.deck_code;
          deckSec.style.display = 'block';
          deckBtn.onclick = function() {
            navigator.clipboard.writeText(radar.deck_code);
            deckBtn.textContent = 'Скопировано!';
            deckBtn.style.background = '#ff9f1c';
            deckBtn.style.color = '#000';
            setTimeout(function() {
              deckBtn.textContent = 'Копировать';
              deckBtn.style.background = '#2ec4b6';
              deckBtn.style.color = '#fff';
            }, 1500);
          };
        } else {
          deckSec.style.display = 'none';
        }
      }

      nodes = radar.nodes.map(function(n) {
        var angle = Math.random() * Math.PI * 2;
        var radius = 150 + Math.random() * 100;
        return Object.assign({}, n, {
          x: 375 + Math.cos(angle) * radius,
          y: 375 + Math.sin(angle) * radius,
          vx: 0,
          vy: 0,
          linksCount: radar.edges.filter(function(e) { return e.source === n.name || e.target === n.name; }).length
        });
      });

      edges = radar.edges.map(function(e) { return Object.assign({}, e); });
      updateNodesTable();
    }

    function updateNodesTable() {
      if (!nodesTableBody) return;
      nodesTableBody.innerHTML = '';
      
      var sortedNodes = [].concat(nodes).sort(function(a, b) { return b.radius - a.radius; });
      
      sortedNodes.forEach(function(n) {
        var tr = document.createElement('tr');
        tr.style.cursor = 'pointer';
        tr.innerHTML = 
          '<td style="padding: 6px 8px; border-bottom: 1px solid #2d2d38;"><strong>' + escapeHtml(n.name) + '</strong></td>' +
          '<td style="padding: 6px 8px; border-bottom: 1px solid #2d2d38;">' + n.radius.toFixed(1) + '</td>' +
          '<td style="padding: 6px 8px; border-bottom: 1px solid #2d2d38;">' + n.linksCount + '</td>';
          
        tr.addEventListener('click', function() {
          var matchingNode = nodes.find(function(node) { return node.name === n.name; });
          if (matchingNode) {
            selectedNode = matchingNode;
            updateSelectedCardView();
          }
        });
        nodesTableBody.appendChild(tr);
      });
    }

    function updateSelectedCardView() {
      if (!cardTitle || !cardDetails) return;
      
      if (!selectedNode) {
        cardTitle.textContent = 'Выберите карту на графе';
        cardDetails.innerHTML = '<p class="muted" style="color: #888;">Нажмите на любой узел на графе, чтобы увидеть его сильные связи с другими картами.</p>';
        return;
      }

      cardTitle.textContent = selectedNode.name;
      
      var conn = edges
        .filter(function(e) { return e.source === selectedNode.name || e.target === selectedNode.name; })
        .map(function(e) {
          var other = e.source === selectedNode.name ? e.target : e.source;
          return { name: other, weight: e.weight };
        })
        .sort(function(a, b) { return b.weight - a.weight; })
        .slice(0, 10);

      var html = '<p style="margin: 4px 0;"><strong>Популярность (радиус):</strong> ' + selectedNode.radius.toFixed(1) + '</p>';
      html += '<h5 style="margin: 12px 0 6px 0; border-bottom: 1px solid #333; padding-bottom: 4px; font-size: 0.85rem; color: #ff9f1c;">Топ-10 сильнейших связей:</h5>';
      if (conn.length === 0) {
        html += '<p class="muted" style="color: #666;">Связи не найдены.</p>';
      } else {
        html += '<ul style="margin: 0; padding-left: 15px; line-height: 1.4; font-size: 0.8rem; color: #ddd;">';
        conn.forEach(function(c) {
          html += '<li style="margin-bottom: 3px;"><strong>' + escapeHtml(c.name) + '</strong> (сила связи: ' + (c.weight * 100).toFixed(0) + '%)</li>';
        });
        html += '</ul>';
      }

      cardDetails.innerHTML = html;
    }

    function getMousePos(evt) {
      var rect = canvas.getBoundingClientRect();
      return {
        x: (evt.clientX - rect.left) * (750 / rect.width),
        y: (evt.clientY - rect.top) * (750 / rect.height)
      };
    }

    // Capture previous listeners using DOM node replacement
    var newCanvas = canvas.cloneNode(true);
    canvas.parentNode.replaceChild(newCanvas, canvas);
    canvas = newCanvas;

    canvas.addEventListener('mousedown', function(e) {
      var pos = getMousePos(e);
      var clicked = null;
      for (var i = 0; i < nodes.length; i++) {
        var n = nodes[i];
        var dx = n.x - pos.x;
        var dy = n.y - pos.y;
        var dist = Math.sqrt(dx * dx + dy * dy);
        if (dist <= n.radius + 5) {
          clicked = n;
          break;
        }
      }

      if (clicked) {
        draggedNode = clicked;
        selectedNode = clicked;
        updateSelectedCardView();
        canvas.style.cursor = 'grabbing';
      }
    });

    canvas.addEventListener('mousemove', function(e) {
      var pos = getMousePos(e);
      
      if (draggedNode) {
        draggedNode.x = pos.x;
        draggedNode.y = pos.y;
        draggedNode.vx = 0;
        draggedNode.vy = 0;
      } else {
        var found = null;
        for (var i = 0; i < nodes.length; i++) {
          var n = nodes[i];
          var dx = n.x - pos.x;
          var dy = n.y - pos.y;
          var dist = Math.sqrt(dx * dx + dy * dy);
          if (dist <= n.radius + 5) {
            found = n;
            break;
          }
        }

        hoveredNode = found;
        if (found) {
          canvas.style.cursor = 'pointer';
          if (hoverInfo) {
            hoverInfo.innerHTML = 'Карта: <strong style="color: #ff9f1c">' + escapeHtml(found.name) + '</strong> · Популярность: ' + found.radius.toFixed(1) + ' · Связей: ' + found.linksCount;
          }
        } else {
          canvas.style.cursor = 'grab';
          if (hoverInfo) {
            hoverInfo.textContent = 'Наведите на карту для деталей';
          }
        }
      }
    });

    window.addEventListener('mouseup', function() {
      if (draggedNode) {
        draggedNode = null;
        canvas.style.cursor = 'grab';
      }
    });

    // Touch Support
    canvas.addEventListener('touchstart', function(e) {
      if (e.touches.length > 0) {
        var touch = e.touches[0];
        var mouseEvent = new MouseEvent('mousedown', {
          clientX: touch.clientX,
          clientY: touch.clientY
        });
        canvas.dispatchEvent(mouseEvent);
      }
    }, { passive: true });

    canvas.addEventListener('touchmove', function(e) {
      if (e.touches.length > 0) {
        var touch = e.touches[0];
        var mouseEvent = new MouseEvent('mousemove', {
          clientX: touch.clientX,
          clientY: touch.clientY
        });
        canvas.dispatchEvent(mouseEvent);
      }
    }, { passive: true });

    canvas.addEventListener('touchend', function() {
      var mouseEvent = new MouseEvent('mouseup', {});
      window.dispatchEvent(mouseEvent);
    });

    rebuildArchetypeTabs(currentClass);
    loadClassRadar(currentClass, null);

    // Cancel any previous animation for this slot
    if (activeAnimations.has(wrapperIndex)) {
      cancelAnimationFrame(activeAnimations.get(wrapperIndex));
    }

    function tick() {
      var centerX = 375;
      var centerY = 375;
      
      for (var i = 0; i < nodes.length; i++) {
        var n1 = nodes[i];
        var cdx = centerX - n1.x;
        var cdy = centerY - n1.y;
        var cdist = Math.sqrt(cdx * cdx + cdy * cdy) || 1;
        n1.vx += (cdx / cdist) * 0.15;
        n1.vy += (cdy / cdist) * 0.15;

        for (var j = i + 1; j < nodes.length; j++) {
          var n2 = nodes[j];
          var dx = n2.x - n1.x;
          var dy = n2.y - n1.y;
          var dist = Math.sqrt(dx * dx + dy * dy) || 1;
          var minDist = n1.radius + n2.radius + 35;
          if (dist < minDist) {
            var force = (minDist - dist) * 0.4;
            var fx = (dx / dist) * force;
            var fy = (dy / dist) * force;
            n1.vx -= fx;
            n1.vy -= fy;
            n2.vx += fx;
            n2.vy += fy;
          }
        }
      }

      for (var k = 0; k < edges.length; k++) {
        var e = edges[k];
        var sourceNode = nodes.find(function(n) { return n.name === e.source; });
        var targetNode = nodes.find(function(n) { return n.name === e.target; });
        if (sourceNode && targetNode) {
          var dx = targetNode.x - sourceNode.x;
          var dy = targetNode.y - sourceNode.y;
          var dist = Math.sqrt(dx * dx + dy * dy) || 1;
          
          if (e.weight > 0.1) {
            var desiredLen = e.length || 220;
            var springK = 0.015 * e.weight;
            var force = (dist - desiredLen) * springK;
            var fx = (dx / dist) * force;
            var fy = (dy / dist) * force;
            sourceNode.vx += fx;
            sourceNode.vy += fy;
            targetNode.vx -= fx;
            targetNode.vy -= fy;
          }
        }
      }

      for (var m = 0; m < nodes.length; m++) {
        var n = nodes[m];
        if (n === draggedNode) continue;

        n.vx *= 0.85;
        n.vy *= 0.85;

        n.x += n.vx;
        n.y += n.vy;

        var margin = n.radius + 10;
        if (n.x < margin) { n.x = margin; n.vx = -n.vx * 0.5; }
        if (n.x > 750 - margin) { n.x = 750 - margin; n.vx = -n.vx * 0.5; }
        if (n.y < margin) { n.y = margin; n.vy = -n.vy * 0.5; }
        if (n.y > 750 - margin) { n.y = 750 - margin; n.vy = -n.vy * 0.5; }
      }

      ctx.clearRect(0, 0, 750, 750);

      // Draw Edges
      for (var eIndex = 0; eIndex < edges.length; eIndex++) {
        var edgeObj = edges[eIndex];
        var sourceNode = nodes.find(function(n) { return n.name === edgeObj.source; });
        var targetNode = nodes.find(function(n) { return n.name === edgeObj.target; });
        if (!sourceNode || !targetNode) continue;

        var opacity = edgeObj.weight * 0.5;
        var isEdgeHighlighted = false;

        if (searchText) {
          var sMatch = sourceNode.name.toLowerCase().indexOf(searchText) !== -1;
          var tMatch = targetNode.name.toLowerCase().indexOf(searchText) !== -1;
          if (sMatch && tMatch) {
            isEdgeHighlighted = true;
            opacity = Math.min(1.0, edgeObj.weight * 1.5);
          } else {
            opacity = 0.02;
          }
        } else if (selectedNode) {
          if (sourceNode.name === selectedNode.name || targetNode.name === selectedNode.name) {
            isEdgeHighlighted = true;
            opacity = Math.min(0.9, edgeObj.weight * 1.8);
          } else {
            opacity = 0.02;
          }
        } else {
          if (edgeObj.weight < 0.15) continue;
        }

        ctx.beginPath();
        ctx.moveTo(sourceNode.x, sourceNode.y);
        ctx.lineTo(targetNode.x, targetNode.y);
        ctx.lineWidth = isEdgeHighlighted ? 2.5 : 1.0;
        ctx.strokeStyle = isEdgeHighlighted ? 'rgba(255, 159, 28, ' + opacity + ')' : 'rgba(255, 255, 255, ' + opacity + ')';
        ctx.stroke();
      }

      // Draw Nodes
      for (var nIndex = 0; nIndex < nodes.length; nIndex++) {
        var nodeObj = nodes[nIndex];
        var isNodeHighlighted = true;
        var drawBorder = false;

        if (searchText) {
          isNodeHighlighted = nodeObj.name.toLowerCase().indexOf(searchText) !== -1;
        } else if (selectedNode) {
          isNodeHighlighted = (nodeObj.name === selectedNode.name || edges.some(function(e) { 
            return (e.source === selectedNode.name && e.target === nodeObj.name) || 
                   (e.target === selectedNode.name && e.source === nodeObj.name);
          }));
          drawBorder = (nodeObj.name === selectedNode.name);
        }

        var baseAlpha = isNodeHighlighted ? 0.9 : 0.2;
        var strokeAlpha = isNodeHighlighted ? 1.0 : 0.2;

        var fillStyle = nodeObj.fill || 'rgba(0,102,0,0.75)';
        var strokeStyle = nodeObj.stroke || 'rgba(221,221,221,1.00)';
        
        fillStyle = fillStyle.replace(/[\d.]+\)$/, baseAlpha + ')');
        strokeStyle = strokeStyle.replace(/[\d.]+\)$/, strokeAlpha + ')');

        if (drawBorder) {
          ctx.beginPath();
          ctx.arc(nodeObj.x, nodeObj.y, nodeObj.radius + 6, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(255, 159, 28, 0.3)';
          ctx.fill();
        }

        ctx.beginPath();
        ctx.arc(nodeObj.x, nodeObj.y, nodeObj.radius, 0, Math.PI * 2);
        ctx.fillStyle = fillStyle;
        ctx.fill();
        ctx.lineWidth = nodeObj.strokewidth || 2.0;
        ctx.strokeStyle = drawBorder ? '#ff9f1c' : strokeStyle;
        ctx.stroke();

        ctx.font = 'bold ' + (nodeObj.radius < 10 ? 10 : 12) + 'px sans-serif';
        ctx.fillStyle = isNodeHighlighted ? 'rgba(255,255,255,1.00)' : 'rgba(255,255,255,0.25)';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        
        ctx.shadowColor = 'rgba(0, 0, 0, 0.9)';
        ctx.shadowBlur = 4;
        ctx.fillText(nodeObj.name, nodeObj.x, nodeObj.y);
        ctx.shadowBlur = 0;
      }

      var nextAnim = requestAnimationFrame(tick);
      activeAnimations.set(wrapperIndex, nextAnim);
    }

    tick();
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

})();
