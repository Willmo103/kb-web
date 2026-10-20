/**
 * jinja_highlighter.js
 * Reusable Jinja2 parameter syntax & dataset field validation highlighter.
 * 
 * Features:
 * - Real-time syntax validation:
 *   - Green highlighting & badges for valid fields (e.g. {{ data.title }}, {{ data.url }})
 *   - Red highlighting & badges for unrecognized/invalid fields (e.g. {{ data.nonexistent }})
 * - Interactive Available Fields bar:
 *   - Displays all accessible dataset fields with click-to-insert tokens at cursor position
 * - Backdrop mirror layer for in-editor colored parameter highlighting
 */

(function () {
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
            // Check if already initialized
            if (this.textarea.dataset.highlighterInit === 'true') {
                return;
            }
            this.textarea.dataset.highlighterInit = 'true';

            // Wrap textarea in relative container if not already wrapped
            this.setupEditorDOM();

            // Setup listeners
            this.textarea.addEventListener('input', () => this.update());
            this.textarea.addEventListener('scroll', () => this.syncScroll());
            window.addEventListener('resize', () => this.syncDimensions());

            // Initial render
            this.renderFieldsBar();
            this.update();
        }

        setupEditorDOM() {
            // Container for textarea and mirror overlay
            const parent = this.textarea.parentNode;
            this.wrapper = document.createElement('div');
            this.wrapper.className = 'jinja-editor-wrapper relative w-full';

            // Insert wrapper before textarea, then move textarea into wrapper
            parent.insertBefore(this.wrapper, this.textarea);
            this.wrapper.appendChild(this.textarea);

            // Create backdrop highlight layer positioned behind textarea
            this.backdrop = document.createElement('div');
            this.backdrop.className = 'jinja-backdrop pointer-events-none absolute inset-0 font-mono text-xs overflow-hidden select-none border border-transparent box-border rounded-xl p-3.5';
            this.backdrop.style.whiteSpace = 'pre-wrap';
            this.backdrop.style.wordBreak = 'break-word';
            this.backdrop.style.color = 'transparent';
            this.backdrop.style.zIndex = '1';

            this.wrapper.insertBefore(this.backdrop, this.textarea);

            // Style textarea to be transparent so highlights show through cleanly
            this.textarea.style.position = 'relative';
            this.textarea.style.zIndex = '2';
            this.textarea.style.backgroundColor = 'transparent';

            // Create Fields Bar if container specified or append below textarea
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
            label.innerHTML = '<span>🏷️</span> Available Dataset Fields:';
            this.fieldsBar.appendChild(label);

            if (this.availableFields.size === 0) {
                const emptyBadge = document.createElement('span');
                emptyBadge.className = 'text-[11px] text-gray-400 italic';
                emptyBadge.innerText = 'No dataset selected or no columns available';
                this.fieldsBar.appendChild(emptyBadge);
                return;
            }

            const sortedFields = Array.from(this.availableFields).sort();
            for (const field of sortedFields) {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'px-2 py-0.5 rounded text-[11px] font-mono font-medium bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200 transition cursor-pointer flex items-center gap-1 shadow-2xs';
                btn.title = `Click to insert {{ data.${field} }}`;
                btn.innerHTML = `<span class="text-indigo-400 font-bold">+</span> {{ data.${this.escapeHtml(field)} }}`;
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
                // Non-matched plain text before this match
                const plainText = text.substring(lastIndex, match.index);
                highlightedHtml += this.escapeHtml(plainText);

                const rawExpr = match[0];
                const varPath = match[1];

                // Extract field name (handle both `data.field_name` and direct `field_name`)
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
                    // Green highlight for proper assignment
                    highlightedHtml += `<mark class="jinja-param-green" style="background-color: #bbf7d0; color: #14532d; border-radius: 3px; padding: 1px 3px; font-weight: bold; border: 1px solid #86efac;">${this.escapeHtml(rawExpr)}</mark>`;
                } else {
                    // Red highlight for incorrect or non-matching parameter
                    highlightedHtml += `<mark class="jinja-param-red" style="background-color: #fecaca; color: #7f1d1d; border-radius: 3px; padding: 1px 3px; font-weight: bold; border: 1px solid #fca5a5;" title="Unrecognized field '${fieldName}'">${this.escapeHtml(rawExpr)}</mark>`;
                }

                lastIndex = regex.lastIndex;
            }

            // Append remaining plain text
            highlightedHtml += this.escapeHtml(text.substring(lastIndex));

            // Trailing newline fix for pre-wrap mirror scrolling
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

            // Deduplicate parameters
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
            this.syncScroll();
        }
    }

    // Expose globally
    window.JinjaHighlighter = JinjaHighlighter;

    window.initJinjaHighlighter = function (textareaId, options) {
        return new JinjaHighlighter(textareaId, options);
    };
})();
