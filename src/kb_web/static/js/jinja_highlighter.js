/**
 * jinja_highlighter.js
 * Reusable Jinja2 parameter syntax & dataset field validation highlighter.
 * 
 * Features:
 * - Direct in-textarea parameter syntax highlighting:
 *   - Green glowing pills for valid database/runtime fields (e.g. {{ data.title }}, {{ data.url }})
 *   - Red wavy glowing alert pills for unrecognized/invalid fields (e.g. {{ data.nonexistent }})
 * - Interactive Available Fields Bar:
 *   - Categorized by Database Fields (fetched_pages) and Agent Runtime Parameters
 *   - Click-to-insert tokens at cursor position
 * - Backdrop mirror layer with pixel-accurate layout synchronization and scroll sync
 */

(function () {
    // Inject global highlighter styles once into document head
    function ensureHighlighterStyles() {
        if (document.getElementById('jinja-highlighter-styles')) return;
        const style = document.createElement('style');
        style.id = 'jinja-highlighter-styles';
        style.textContent = `
            .jinja-editor-wrapper {
                position: relative !important;
                width: 100% !important;
                box-sizing: border-box !important;
            }
            .jinja-backdrop {
                position: absolute !important;
                inset: 0 !important;
                pointer-events: none !important;
                overflow: hidden !important;
                user-select: none !important;
                color: transparent !important;
                z-index: 1 !important;
                white-space: pre-wrap !important;
                word-break: break-word !important;
                overflow-wrap: break-word !important;
                box-sizing: border-box !important;
            }
            .jinja-backdrop mark {
                color: transparent !important;
                display: inline !important;
                border-radius: 4px !important;
            }
            .jinja-backdrop mark.jinja-param-green {
                background-color: rgba(34, 197, 94, 0.32) !important;
                box-shadow: 0 0 0 1.5px rgba(34, 197, 94, 0.75) !important;
            }
            .jinja-backdrop mark.jinja-param-red {
                background-color: rgba(239, 68, 68, 0.35) !important;
                box-shadow: 0 0 0 1.5px rgba(239, 68, 68, 0.8) !important;
                text-decoration: underline wavy #ef4444 !important;
            }
            .jinja-editor-wrapper textarea {
                position: relative !important;
                z-index: 2 !important;
                background-color: transparent !important;
                background: transparent !important;
            }
        `;
        document.head.appendChild(style);
    }

    const STANDARD_DB_FIELDS = new Set([
        'title', 'url', 'description', 'md_content', 'content', 'tags', 'reading_time_minutes', 'fetched_at', 'wiki'
    ]);

    class JinjaHighlighter {
        constructor(textarea, options = {}) {
            this.textarea = typeof textarea === 'string' ? document.getElementById(textarea) : textarea;
            if (!this.textarea) {
                console.warn('[JinjaHighlighter] Textarea not found:', textarea);
                return;
            }

            this.options = Object.assign({
                availableFields: [],
                fieldsBarContainerId: null,
                statusBarContainerId: null,
                prefix: 'data.',
                onFieldInserted: null,
            }, options);

            this.availableFields = new Set(this.options.availableFields || []);
            this.init();
        }

        init() {
            if (this.textarea.dataset.highlighterInit === 'true') {
                return;
            }
            this.textarea.dataset.highlighterInit = 'true';

            ensureHighlighterStyles();
            this.setupEditorDOM();

            // Setup event listeners
            this.textarea.addEventListener('input', () => this.update());
            this.textarea.addEventListener('scroll', () => this.syncScroll());
            window.addEventListener('resize', () => this.syncDimensions());

            if (window.ResizeObserver) {
                this.resizeObserver = new ResizeObserver(() => this.syncDimensions());
                this.resizeObserver.observe(this.textarea);
            }

            // Initial render
            this.renderFieldsBar();
            this.syncDimensions();
            this.update();
        }

        setupEditorDOM() {
            const parent = this.textarea.parentNode;
            this.wrapper = document.createElement('div');
            this.wrapper.className = 'jinja-editor-wrapper relative w-full';

            // Preserve background color on the wrapper so transparency doesn't make it blank
            const cs = window.getComputedStyle(this.textarea);
            const bg = cs.backgroundColor;
            if (bg && bg !== 'transparent' && bg !== 'rgba(0, 0, 0, 0)') {
                this.wrapper.style.backgroundColor = bg;
            }
            if (cs.borderRadius) {
                this.wrapper.style.borderRadius = cs.borderRadius;
            }

            parent.insertBefore(this.wrapper, this.textarea);
            this.wrapper.appendChild(this.textarea);

            // Create backdrop highlight layer positioned behind textarea
            this.backdrop = document.createElement('div');
            this.backdrop.className = 'jinja-backdrop pointer-events-none absolute inset-0 select-none overflow-hidden';
            this.applyTextareaMetrics(cs);

            this.wrapper.insertBefore(this.backdrop, this.textarea);

            // Force textarea background to transparent
            this.textarea.style.position = 'relative';
            this.textarea.style.zIndex = '2';
            this.textarea.style.setProperty('background-color', 'transparent', 'important');
            this.textarea.style.setProperty('background', 'transparent', 'important');

            // Create Fields Bar
            if (this.options.fieldsBarContainerId) {
                this.fieldsBar = document.getElementById(this.options.fieldsBarContainerId);
            } else {
                this.fieldsBar = document.createElement('div');
                this.fieldsBar.className = 'jinja-fields-bar mt-2 flex flex-wrap items-center gap-1.5 text-xs';
                this.wrapper.parentNode.insertBefore(this.fieldsBar, this.wrapper.nextSibling);
            }

            // Create Status Badges Bar
            if (this.options.statusBarContainerId) {
                this.statusBar = document.getElementById(this.options.statusBarContainerId);
            } else {
                this.statusBar = document.createElement('div');
                this.statusBar.className = 'jinja-status-bar mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px]';
                this.fieldsBar.parentNode.insertBefore(this.statusBar, this.fieldsBar.nextSibling);
            }
        }

        applyTextareaMetrics(cs) {
            if (!this.backdrop) return;
            this.backdrop.style.fontFamily = cs.fontFamily;
            this.backdrop.style.fontSize = cs.fontSize;
            this.backdrop.style.fontWeight = cs.fontWeight;
            this.backdrop.style.lineHeight = cs.lineHeight;
            this.backdrop.style.letterSpacing = cs.letterSpacing;
            this.backdrop.style.paddingTop = cs.paddingTop;
            this.backdrop.style.paddingRight = cs.paddingRight;
            this.backdrop.style.paddingBottom = cs.paddingBottom;
            this.backdrop.style.paddingLeft = cs.paddingLeft;
            this.backdrop.style.borderTopWidth = cs.borderTopWidth;
            this.backdrop.style.borderRightWidth = cs.borderRightWidth;
            this.backdrop.style.borderBottomWidth = cs.borderBottomWidth;
            this.backdrop.style.borderLeftWidth = cs.borderLeftWidth;
            this.backdrop.style.borderStyle = 'solid';
            this.backdrop.style.borderColor = 'transparent';
            this.backdrop.style.borderRadius = cs.borderRadius;
            this.backdrop.style.boxSizing = cs.boxSizing || 'border-box';
        }

        setAvailableFields(fields) {
            this.availableFields = new Set(Array.isArray(fields) ? fields : []);
            this.renderFieldsBar();
            this.update();
        }

        renderFieldsBar() {
            if (!this.fieldsBar) return;
            this.fieldsBar.innerHTML = '';

            const label = document.createElement('span');
            label.className = 'text-[10px] font-bold uppercase tracking-wider text-gray-500 mr-1 flex items-center gap-1';
            label.innerHTML = '<span>🏷️</span> Available Fields:';
            this.fieldsBar.appendChild(label);

            if (this.availableFields.size === 0) {
                const emptyBadge = document.createElement('span');
                emptyBadge.className = 'text-[11px] text-gray-400 italic';
                emptyBadge.innerText = 'No dataset selected or no columns available';
                this.fieldsBar.appendChild(emptyBadge);
                return;
            }

            const sortedFields = Array.from(this.availableFields).sort((a, b) => {
                const aIsDb = STANDARD_DB_FIELDS.has(a);
                const bIsDb = STANDARD_DB_FIELDS.has(b);
                if (aIsDb && !bIsDb) return -1;
                if (!aIsDb && bIsDb) return 1;
                return a.localeCompare(b);
            });

            for (const field of sortedFields) {
                const isDbField = STANDARD_DB_FIELDS.has(field);
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = isDbField
                    ? 'px-2 py-0.5 rounded text-[11px] font-mono font-medium bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200 transition cursor-pointer flex items-center gap-1 shadow-2xs'
                    : 'px-2 py-0.5 rounded text-[11px] font-mono font-medium bg-amber-50 hover:bg-amber-100 text-amber-800 border border-amber-200 transition cursor-pointer flex items-center gap-1 shadow-2xs';
                btn.title = `Click to insert {{ data.${field} }} (${isDbField ? 'Database field' : 'Runtime parameter'})`;
                btn.innerHTML = `<span class="${isDbField ? 'text-indigo-400' : 'text-amber-500'} font-bold">+</span> {{ data.${this.escapeHtml(field)} }}`;
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    this.insertFieldToken(field);
                });
                this.fieldsBar.appendChild(btn);
            }
        }

        insertFieldToken(field) {
            const token = `{{ data.${field} }}`;
            const start = this.textarea.selectionStart || 0;
            const end = this.textarea.selectionEnd || 0;
            const val = this.textarea.value;

            this.textarea.value = val.substring(0, start) + token + val.substring(end);
            this.textarea.selectionStart = this.textarea.selectionEnd = start + token.length;
            this.textarea.focus();

            this.update();
            if (typeof this.options.onFieldInserted === 'function') {
                this.options.onFieldInserted(field, token);
            }
        }

        escapeHtml(str) {
            return String(str || '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        update() {
            const text = this.textarea.value || '';
            const detectedParams = [];
            const regex = /\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}/g;

            let lastIndex = 0;
            let highlightedHtml = '';
            let match;

            while ((match = regex.exec(text)) !== null) {
                const plainText = text.substring(lastIndex, match.index);
                highlightedHtml += this.escapeHtml(plainText);

                const rawExpr = match[0];
                const varPath = match[1];

                let fieldName = varPath;
                if (varPath.startsWith('data.')) {
                    fieldName = varPath.substring(5);
                }

                const isValid = this.availableFields.size === 0 || this.availableFields.has(fieldName);
                detectedParams.push({
                    raw: rawExpr,
                    fieldName: fieldName,
                    isValid: isValid
                });

                if (isValid) {
                    highlightedHtml += `<mark class="jinja-param-green">${this.escapeHtml(rawExpr)}</mark>`;
                } else {
                    highlightedHtml += `<mark class="jinja-param-red" title="Unrecognized field '${this.escapeHtml(fieldName)}'">${this.escapeHtml(rawExpr)}</mark>`;
                }

                lastIndex = regex.lastIndex;
            }

            highlightedHtml += this.escapeHtml(text.substring(lastIndex));

            if (text.endsWith('\n')) {
                highlightedHtml += ' ';
            }

            if (this.backdrop) {
                this.backdrop.innerHTML = highlightedHtml;
                this.syncScroll();
            }

            this.renderStatusBadges(detectedParams);
        }

        renderStatusBadges(params) {
            if (!this.statusBar) return;
            this.statusBar.innerHTML = '';

            if (params.length === 0) {
                this.statusBar.innerHTML = '<span class="text-gray-400 italic">No Jinja parameters detected in template.</span>';
                return;
            }

            const header = document.createElement('span');
            header.className = 'text-[10px] font-bold uppercase tracking-wider text-gray-500 mr-1';
            header.innerText = 'Template Variables:';
            this.statusBar.appendChild(header);

            const seen = new Set();
            for (const p of params) {
                if (seen.has(p.raw)) continue;
                seen.add(p.raw);

                const pill = document.createElement('span');
                pill.className = `inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-mono text-[10px] font-bold ${
                    p.isValid
                        ? 'bg-emerald-100 text-emerald-800 border border-emerald-300'
                        : 'bg-red-100 text-red-800 border border-red-300'
                }`;
                pill.innerHTML = p.isValid
                    ? `<span>✓</span> ${this.escapeHtml(p.raw)}`
                    : `<span>✗</span> ${this.escapeHtml(p.raw)} <span class="font-normal opacity-75">(invalid field)</span>`;
                this.statusBar.appendChild(pill);
            }
        }

        syncScroll() {
            if (!this.backdrop || !this.textarea) return;
            this.backdrop.scrollTop = this.textarea.scrollTop;
            this.backdrop.scrollLeft = this.textarea.scrollLeft;
        }

        syncDimensions() {
            if (!this.backdrop || !this.textarea) return;
            const cs = window.getComputedStyle(this.textarea);
            this.applyTextareaMetrics(cs);
            this.backdrop.style.width = this.textarea.clientWidth + 'px';
            this.backdrop.style.height = this.textarea.clientHeight + 'px';
            this.syncScroll();
        }
    }

    // Expose globally
    window.JinjaHighlighter = JinjaHighlighter;

    window.initJinjaHighlighter = function (textareaId, options) {
        return new JinjaHighlighter(textareaId, options);
    };
})();
