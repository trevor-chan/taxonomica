// Taxonomica Game - Frontend Logic

class TaxonomicaGame {
    constructor() {
        this.currentScreen = 'setup';
        this.difficulty = 'medium';
        this.seed = '';
        this.roundNumber = 1;
        this.choices = [];
        this.cumulativeScore = 0;
        this.roundScores = [];
        
        // Pagination
        this.pageSize = 26;
        this.currentPage = 0;
        
        // Sort mode: 0 = by descendants, 1 = alphabetical, 2 = by rank
        this.sortMode = 0;
        
        // Current game state from server
        this.gameState = null;
        
        this.initEventListeners();
    }
    
    initEventListeners() {
        // Setup screen
        document.querySelectorAll('.difficulty-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.selectDifficulty(e.target.dataset.difficulty));
        });
        
        document.getElementById('start-btn').addEventListener('click', () => this.startGame());
        document.getElementById('seed-input').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.startGame();
        });
        
        // Game screen - command input
        const commandInput = document.getElementById('command-input');
        commandInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.processCommand();
        });
        document.getElementById('submit-btn').addEventListener('click', () => this.processCommand());
        
        // Victory screen
        document.getElementById('play-again-btn').addEventListener('click', () => this.playAgain());
        document.getElementById('new-game-btn').addEventListener('click', () => this.newGame());
        
        // Modal close
        document.querySelector('.modal-close').addEventListener('click', () => this.closeModal());
        document.getElementById('info-modal').addEventListener('click', (e) => {
            if (e.target.id === 'info-modal') this.closeModal();
        });
        
        // Global keyboard handler (for setup/victory screens)
        document.addEventListener('keydown', (e) => this.handleGlobalKeypress(e));
    }
    
    selectDifficulty(difficulty) {
        this.difficulty = difficulty;
        document.querySelectorAll('.difficulty-btn').forEach(btn => {
            btn.classList.toggle('selected', btn.dataset.difficulty === difficulty);
        });
    }
    
    showScreen(screenId) {
        document.querySelectorAll('.screen').forEach(s => s.classList.add('hidden'));
        document.getElementById(screenId).classList.remove('hidden');
        this.currentScreen = screenId.replace('-screen', '');
        
        // Focus command input when game screen is shown
        if (screenId === 'game-screen') {
            setTimeout(() => {
                document.getElementById('command-input').focus();
            }, 100);
        }
    }
    
    async startGame() {
        this.seed = document.getElementById('seed-input').value.trim();
        this.currentPage = 0;
        
        this.showScreen('loading-screen');
        
        try {
            const response = await fetch('/api/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    difficulty: this.difficulty,
                    seed: this.seed,
                    round: this.roundNumber,
                }),
            });
            
            const data = await response.json();
            
            if (data.error) {
                alert('Error: ' + data.error);
                this.showScreen('setup-screen');
                return;
            }
            
            this.gameState = data;
            this.updateGameScreen(data);
            this.showScreen('game-screen');
            
        } catch (error) {
            console.error('Error starting game:', error);
            alert('Failed to start game. Is the server running?');
            this.showScreen('setup-screen');
        }
    }
    
    updateGameScreen(data) {
        this.gameState = data;
        
        // Header
        document.getElementById('difficulty-label').textContent = `[${data.difficulty.toUpperCase()}]`;
        if (data.seed_string) {
            document.getElementById('seed-label').textContent = 
                `| Seed: "${data.seed_string}" Round ${data.round_number}`;
        } else {
            document.getElementById('seed-label').textContent = '';
        }
        
        // Stats
        document.getElementById('score').textContent = data.score;
        document.getElementById('progress').textContent = data.progress;
        
        // Path
        if (data.revealed_path && data.revealed_path.length > 0) {
            const pathStr = data.revealed_path.map(n => {
                let s = n.name;
                if (n.vernacular) s += ` "${n.vernacular}"`;
                return s;
            }).join(' → ');
            document.getElementById('revealed-path').textContent = pathStr;
        } else {
            document.getElementById('revealed-path').textContent = '';
        }
        
        // Description
        document.getElementById('description').textContent = data.description;
        document.getElementById('lines-info').textContent = 
            `(showing ${data.visible_lines}/${data.total_lines} lines)`;
        
        // Choices
        this.choices = data.choices;
        this.sortChoices();
        this.renderChoices(data.current_rank, data.guesses_left || 5);
        
        // Clear command input
        document.getElementById('command-input').value = '';
        document.getElementById('command-input').focus();
    }
    
    sortChoices() {
        if (this.sortMode === 0) {
            // By descendants (descending)
            this.choices.sort((a, b) => b.descendants - a.descendants || a.name.localeCompare(b.name));
        } else if (this.sortMode === 1) {
            // Alphabetical
            this.choices.sort((a, b) => a.name.localeCompare(b.name));
        }
        // Mode 2 would be by rank, but all choices are same rank
    }
    
    renderChoices(rank, guessesLeft) {
        const sortNames = ['by descendants', 'alphabetically', 'by rank'];
        document.getElementById('rank-prompt').textContent = 
            `Choose the correct ${rank.toUpperCase()}: (${guessesLeft} guesses left, sorted: ${sortNames[this.sortMode]})`;
        
        const container = document.getElementById('choices');
        container.innerHTML = '';
        
        // Calculate pagination
        const totalPages = Math.ceil(this.choices.length / this.pageSize);
        const startIdx = this.currentPage * this.pageSize;
        const endIdx = Math.min(startIdx + this.pageSize, this.choices.length);
        const pageChoices = this.choices.slice(startIdx, endIdx);
        
        pageChoices.forEach((choice, index) => {
            const key = String.fromCharCode(97 + index); // a, b, c, ...
            const div = document.createElement('div');
            div.className = 'choice-btn';
            div.dataset.id = choice.id;
            div.dataset.key = key;
            
            div.innerHTML = `
                <span class="choice-key">${key}</span>
                <span class="choice-name">${choice.name}</span>
                <span class="choice-vernacular">${choice.vernacular ? `"${choice.vernacular}"` : ''}</span>
                <span class="choice-count">(${choice.descendants.toLocaleString()})</span>
            `;
            
            // Allow clicking as well
            div.addEventListener('click', () => {
                document.getElementById('command-input').value = key;
                this.processCommand();
            });
            
            container.appendChild(div);
        });
        
        // Update pagination
        const pagination = document.getElementById('pagination');
        if (totalPages > 1) {
            pagination.classList.remove('hidden');
            document.getElementById('page-info').textContent = 
                `Page ${this.currentPage + 1} of ${totalPages} (${this.choices.length} total) - [N]ext / [P]rev`;
        } else {
            pagination.classList.add('hidden');
        }
    }
    
    processCommand() {
        const input = document.getElementById('command-input').value.trim();
        if (!input) return;
        
        console.log('Processing command:', input);
        
        // Single character commands - check case sensitivity
        if (input.length === 1) {
            const char = input;
            const isUppercase = char === char.toUpperCase() && char !== char.toLowerCase();
            
            // Uppercase single chars are commands
            if (isUppercase) {
                if (char === 'Q') {
                    if (confirm('Quit game?')) {
                        this.newGame();
                    }
                    document.getElementById('command-input').value = '';
                    return;
                }
                
                if (char === 'I') {
                    this.showInfo(null);
                    document.getElementById('command-input').value = '';
                    return;
                }
                
                if (char === 'N') {
                    const totalPages = Math.ceil(this.choices.length / this.pageSize);
                    if (this.currentPage < totalPages - 1) {
                        this.currentPage++;
                        const rank = this.gameState?.current_rank || 'unknown';
                        const guessesLeft = this.gameState?.guesses_left || 5;
                        this.renderChoices(rank, guessesLeft);
                    } else {
                        this.showFeedbackMessage('Already on last page', 'wrong');
                    }
                    document.getElementById('command-input').value = '';
                    return;
                }
                
                if (char === 'P') {
                    if (this.currentPage > 0) {
                        this.currentPage--;
                        const rank = this.gameState?.current_rank || 'unknown';
                        const guessesLeft = this.gameState?.guesses_left || 5;
                        this.renderChoices(rank, guessesLeft);
                    } else {
                        this.showFeedbackMessage('Already on first page', 'wrong');
                    }
                    document.getElementById('command-input').value = '';
                    return;
                }
                
                if (char === 'S') {
                    this.sortMode = (this.sortMode + 1) % 2;
                    this.currentPage = 0;
                    this.sortChoices();
                    this.renderChoices(this.gameState.current_rank, this.gameState.guesses_left || 5);
                    document.getElementById('command-input').value = '';
                    return;
                }
            }
            
            // Lowercase single chars are selections (a-z)
            const letter = char.toLowerCase();
            if (letter >= 'a' && letter <= 'z') {
                const index = letter.charCodeAt(0) - 97;
                const absoluteIdx = this.currentPage * this.pageSize + index;
                if (absoluteIdx < this.choices.length) {
                    this.makeGuess(this.choices[absoluteIdx].id);
                } else {
                    this.showFeedbackMessage('Invalid choice.', 'wrong');
                }
                document.getElementById('command-input').value = '';
                return;
            }
        }
        
        // Two character commands (I + letter for info on specific choice)
        if (input.length === 2) {
            const first = input[0];
            const second = input[1].toLowerCase();
            
            // I + letter = info on that choice
            if (first === 'I' || first === 'i') {
                if (second >= 'a' && second <= 'z') {
                    const index = second.charCodeAt(0) - 97;
                    const absoluteIdx = this.currentPage * this.pageSize + index;
                    if (absoluteIdx < this.choices.length) {
                        if (this.gameState.current_rank === 'species') {
                            this.showFeedbackMessage('Info not available for species choices.', 'wrong');
                        } else {
                            this.showInfo(this.choices[absoluteIdx].id);
                        }
                    }
                }
                document.getElementById('command-input').value = '';
                return;
            }
        }
        
        document.getElementById('command-input').value = '';
    }
    
    showFeedbackMessage(message, type) {
        const feedback = document.getElementById('feedback');
        feedback.classList.remove('hidden', 'correct', 'wrong', 'guess-cap');
        feedback.classList.add(type);
        feedback.textContent = message;
        
        setTimeout(() => {
            feedback.classList.add('hidden');
        }, 3000);
    }
    
    async makeGuess(choiceId) {
        try {
            const response = await fetch('/api/guess', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ choice_id: choiceId }),
            });
            
            const data = await response.json();
            
            if (data.error) {
                alert('Error: ' + data.error);
                return;
            }
            
            // Show feedback
            this.showFeedback(data);
            
            // Handle game completion
            if (data.complete) {
                setTimeout(() => this.showVictory(data), 3000);
                return;
            }
            
            // Reset page when advancing
            if (data.correct || data.guess_cap) {
                this.currentPage = 0;
            }
            
            // Update screen after delay for feedback (3 seconds)
            setTimeout(() => {
                this.hideFeedback();
                this.updateGameScreen({
                    ...data,
                    difficulty: this.difficulty,
                    seed_string: this.seed,
                    round_number: this.roundNumber,
                });
            }, 3000);
            
        } catch (error) {
            console.error('Error making guess:', error);
        }
    }
    
    showFeedback(data) {
        const feedback = document.getElementById('feedback');
        feedback.classList.remove('hidden', 'correct', 'wrong', 'guess-cap');
        
        if (data.correct) {
            feedback.classList.add('correct');
            feedback.textContent = '✓ Correct!';
        } else if (data.guess_cap) {
            feedback.classList.add('guess-cap');
            const answer = data.correct_answer;
            let text = `✗ Out of guesses! The answer was: ${answer.name}`;
            if (answer.vernacular) text += ` "${answer.vernacular}"`;
            text += ' (+3 penalty)';
            feedback.textContent = text;
        } else {
            feedback.classList.add('wrong');
            feedback.textContent = `✗ Wrong! (${data.guesses_left} guesses left) +1 line revealed`;
        }
    }
    
    hideFeedback() {
        document.getElementById('feedback').classList.add('hidden');
    }
    
    showVictory(data) {
        // Update cumulative score for seeded games
        if (this.seed) {
            this.roundScores.push({ score: data.score, species: data.target_name });
            this.cumulativeScore += data.score;
        }
        
        // Final score
        let scoreHtml = `
            <div class="score-number">${data.score}</div>
            <div>points (${data.guesses} guesses)</div>
        `;
        
        // Score tier message
        if (data.score === 0) {
            scoreHtml += `<div class="score-tier">🏆 PERFECT GAME!</div>`;
        } else if (data.score <= 7) {
            scoreHtml += `<div class="score-tier">⭐ Excellent taxonomy knowledge!</div>`;
        } else if (data.score <= 14) {
            scoreHtml += `<div class="score-tier">👍 Good job!</div>`;
        } else {
            scoreHtml += `<div class="score-tier">📚 Keep studying taxonomy!</div>`;
        }
        
        // Rank title
        if (data.rank_title) {
            scoreHtml += `<div class="rank-title">🎖️ You've attained the rank of: <strong>${data.rank_title}</strong></div>`;
        }
        
        document.getElementById('final-score').innerHTML = scoreHtml;
        
        // Species reveal
        document.getElementById('species-reveal').innerHTML = `
            <div class="species-name">${data.target_name}</div>
            ${data.target_vernacular ? `<div class="vernacular-name">"${data.target_vernacular}"</div>` : ''}
        `;
        
        // Full path
        const pathContainer = document.getElementById('full-path');
        pathContainer.innerHTML = '<h4>Complete Taxonomy:</h4>';
        data.correct_path.forEach(node => {
            if (['kingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species'].includes(node.rank)) {
                const div = document.createElement('div');
                div.className = 'path-item';
                div.innerHTML = `
                    <span class="rank">${node.rank}</span>
                    <span class="name">${node.name}${node.vernacular ? ` "${node.vernacular}"` : ''}</span>
                `;
                pathContainer.appendChild(div);
            }
        });
        
        // Session summary for seeded games
        const summaryContainer = document.getElementById('session-summary');
        if (this.seed && this.roundScores.length > 0) {
            summaryContainer.classList.remove('hidden');
            let html = `<h4>🎮 Session: "${this.seed}" | ${this.difficulty.toUpperCase()}</h4>`;
            this.roundScores.forEach((r, i) => {
                html += `<div class="round-score"><span>Round ${i + 1}: ${r.species}</span><span>${r.score} pts</span></div>`;
            });
            html += `<div class="total"><span>TOTAL (${this.roundScores.length} rounds)</span><span>${this.cumulativeScore} pts</span></div>`;
            summaryContainer.innerHTML = html;
        } else {
            summaryContainer.classList.add('hidden');
        }
        
        this.showScreen('victory-screen');
    }
    
    playAgain() {
        // Keep seed and difficulty, increment round
        this.roundNumber++;
        this.currentPage = 0;
        this.startGame();
    }
    
    newGame() {
        // Reset everything
        this.roundNumber = 1;
        this.cumulativeScore = 0;
        this.roundScores = [];
        this.currentPage = 0;
        document.getElementById('seed-input').value = '';
        this.showScreen('setup-screen');
    }
    
    async showInfo(nodeId) {
        try {
            const url = nodeId ? `/api/info/${nodeId}` : '/api/current_info';
            const response = await fetch(url);
            const data = await response.json();
            
            if (data.error) {
                return;
            }
            
            document.getElementById('info-title').textContent = 
                `📖 ${data.name}${data.vernacular ? ` "${data.vernacular}"` : ''}`;
            
            let body = `<div class="info-meta">`;
            body += `<div>Rank: ${data.rank}</div>`;
            body += `<div>Descendants: ${data.descendants.toLocaleString()}</div>`;
            body += `</div>`;
            
            if (data.description) {
                body += `<div class="info-description">${data.description}</div>`;
            } else {
                body += `<div class="info-description">(No description available)</div>`;
            }
            
            document.getElementById('info-body').innerHTML = body;
            document.getElementById('info-modal').classList.remove('hidden');
            
        } catch (error) {
            console.error('Error fetching info:', error);
        }
    }
    
    closeModal() {
        document.getElementById('info-modal').classList.add('hidden');
        // Refocus command input
        if (this.currentScreen === 'game') {
            document.getElementById('command-input').focus();
        }
    }
    
    handleGlobalKeypress(e) {
        // Don't handle if typing in an input (except for specific cases)
        if (e.target.tagName === 'INPUT') {
            return;
        }
        
        // Modal is open - Escape to close
        if (!document.getElementById('info-modal').classList.contains('hidden')) {
            if (e.key === 'Escape' || e.key === 'Enter') {
                this.closeModal();
            }
            return;
        }
        
        // Setup screen
        if (this.currentScreen === 'setup') {
            if (e.key >= '1' && e.key <= '4') {
                const difficulties = ['easy', 'medium', 'hard', 'expert'];
                this.selectDifficulty(difficulties[parseInt(e.key) - 1]);
            } else if (e.key === 'Enter') {
                this.startGame();
            }
            return;
        }
        
        // Victory screen
        if (this.currentScreen === 'victory') {
            if (e.key === 'Enter' || e.key.toLowerCase() === 'y') {
                this.playAgain();
            } else if (e.key.toLowerCase() === 'n') {
                this.newGame();
            }
        }
    }
}

// Initialize game when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.game = new TaxonomicaGame();
});
