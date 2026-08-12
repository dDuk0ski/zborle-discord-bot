import { ChartBarIcon, InformationCircleIcon, QuestionMarkCircleIcon } from '@heroicons/react/24/outline'
import { useCallback, useEffect, useState } from 'react'
import { Alert } from './components/alerts/Alert'
import { Grid } from './components/grid/Grid'
import { Keyboard } from './components/keyboard/Keyboard'
import { AboutModal } from './components/modals/AboutModal'
import { InfoModal } from './components/modals/InfoModal'
import { WinModal } from './components/modals/WinModal'
import { ShortcutsModal } from './components/modals/ShortcutsModal'
import { getTimeUntilNextWord, hasRolledOver, setSchedule } from './lib/words'
import { convert, LETTERS_EN } from './lib/keyboard'
import { toGameStats } from './lib/stats'
import { emptyStats } from './lib/localStorage'
import { recordGuessStatuses, replaceGuessStatuses } from './lib/statuses'
import { fetchState, fetchStats, submitGuess } from './lib/api'
import { startSession, type Session } from './lib/discord'
import { StatsModal } from './components/modals/StatsModals'
import { ThemeToggle } from './components/ui/ThemeToggle'
import { SoundToggle } from './components/ui/SoundToggle'
import { useSound } from './contexts/SoundContext'

const ALERT_MS = 2000

function App() {
    const { playSound } = useSound()
    const [session, setSession] = useState<Session | null>(null)
    const [bootError, setBootError] = useState<string | null>(null)

    const [currentGuess, setCurrentGuess] = useState('')
    const [guesses, setGuesses] = useState<string[]>([])
    const [solution, setSolution] = useState<string | null>(null)
    const [isGameWon, setIsGameWon] = useState(false)
    const [isSubmitting, setIsSubmitting] = useState(false)

    const [isWinModalOpen, setIsWinModalOpen] = useState(false)
    const [isWinAnimationStarted, setIsWinAnimationStarted] = useState(false)
    const [isInfoModalOpen, setIsInfoModalOpen] = useState(false)
    const [isAboutModalOpen, setIsAboutModalOpen] = useState(false)
    const [isShortcutsModalOpen, setIsShortcutsModalOpen] = useState(false)
    const [isStatsModalOpen, setIsStatsModalOpen] = useState(false)
    const [isNotEnoughLetters, setIsNotEnoughLetters] = useState(false)
    const [rejection, setRejection] = useState<string | null>(null)
    const [isGameLost, setIsGameLost] = useState(false)
    const [shareComplete, setShareComplete] = useState(false)

    const [timeUntilNextWord, setTimeUntilNextWord] = useState(getTimeUntilNextWord())
    const [stats, setStats] = useState(emptyStats)

    const refreshStats = useCallback(async () => {
        try {
            setStats(toGameStats(await fetchStats()))
        } catch {
            // Stats are decoration; a failure here must not break the board.
        }
    }, [])

    /** Pull the authoritative board from the server and mirror it into local state. */
    const loadState = useCallback(async () => {
        const state = await fetchState()
        setSchedule(state.puzzleIndex, state.secondsUntilNext)
        replaceGuessStatuses(state.guesses, state.statuses)
        setGuesses(state.guesses)
        setSolution(state.solution)
        setIsGameWon(state.isWon)
        setTimeUntilNextWord(getTimeUntilNextWord())
        if (state.guesses.length === 0) {
            setIsInfoModalOpen(true)
        }
        if (state.isWon) {
            setIsWinAnimationStarted(true)
            setIsWinModalOpen(true)
        }
    }, [])

    // Boot: authenticate with Discord, then load the board. Both must succeed before the
    // grid means anything, so failures surface instead of rendering an empty board.
    useEffect(() => {
        let cancelled = false
        ;(async () => {
            try {
                const active = await startSession()
                if (cancelled) return
                setSession(active)
                await loadState()
                if (!cancelled) await refreshStats()
            } catch (error) {
                if (!cancelled) {
                    setBootError(error instanceof Error ? error.message : 'Неуспешно поврзување.')
                }
            }
        })()
        return () => {
            cancelled = true
        }
    }, [loadState, refreshStats])

    // Countdown, and a refetch when the word rolls over at Skopje midnight.
    useEffect(() => {
        const timer = setInterval(() => {
            setTimeUntilNextWord(getTimeUntilNextWord())
            if (hasRolledOver()) {
                void loadState()
            }
        }, 1000)
        return () => clearInterval(timer)
    }, [loadState])

    useEffect(() => {
        const timeout = setTimeout(() => setIsWinModalOpen(isGameWon), 2500)
        return () => clearTimeout(timeout)
    }, [isGameWon])

    useEffect(() => {
        const timeout = setTimeout(() => setIsWinAnimationStarted(isGameWon), 150 * 5 + 250)
        return () => clearTimeout(timeout)
    }, [isGameWon])

    const flash = (set: (value: boolean) => void) => {
        set(true)
        setTimeout(() => set(false), ALERT_MS)
    }

    const onChar = (value: string) => {
        if (isGameWon || isSubmitting || solution) {
            return
        }
        let converted = value
        if (LETTERS_EN.includes(value)) {
            converted = convert(value)
        }
        if (currentGuess.length < 5 && guesses.length < 6) {
            setCurrentGuess(`${currentGuess}${converted}`)
            playSound('keypress')
        }
    }

    const onDelete = () => {
        if (isSubmitting) return
        setCurrentGuess(currentGuess.slice(0, -1))
        playSound('delete')
    }

    const onEnter = async () => {
        if (isGameWon || isSubmitting || solution) {
            return
        }

        // Length is checked locally purely for instant feedback; the server checks it too.
        if (currentGuess.length !== 5) {
            playSound('invalid')
            flash(setIsNotEnoughLetters)
            return
        }

        setIsSubmitting(true)
        try {
            const result = await submitGuess(currentGuess)

            if (!result.ok) {
                playSound('invalid')
                setRejection(result.message)
                setTimeout(() => setRejection(null), ALERT_MS)
                return
            }

            recordGuessStatuses(currentGuess, result.statuses)
            setGuesses((previous) => [...previous, currentGuess])
            setCurrentGuess('')
            playSound('enter')

            if (result.isWon) {
                setSolution(result.solution)
                setTimeout(() => playSound('win'), 500)
                setIsGameWon(true)
                void refreshStats()
                return
            }

            if (result.isLost) {
                setSolution(result.solution)
                setTimeout(() => playSound('lose'), 500)
                flash(setIsGameLost)
                void refreshStats()
            }
        } catch {
            playSound('invalid')
            setRejection('Серверот не одговори. Обиди се повторно.')
            setTimeout(() => setRejection(null), ALERT_MS)
        } finally {
            setIsSubmitting(false)
        }
    }

    // Keyboard shortcuts
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === '?' && !e.ctrlKey && !e.metaKey && !e.altKey) {
                e.preventDefault()
                setIsShortcutsModalOpen(true)
            }
        }
        window.addEventListener('keydown', handleKeyDown)
        return () => window.removeEventListener('keydown', handleKeyDown)
    }, [])

    if (bootError) {
        return (
            <div className="min-h-screen bg-white dark:bg-slate-900 flex items-center justify-center p-6">
                <div className="max-w-sm text-center">
                    <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100 mb-2">Зборле</h1>
                    <p className="text-slate-600 dark:text-slate-400">{bootError}</p>
                </div>
            </div>
        )
    }

    if (!session) {
        return (
            <div className="min-h-screen bg-white dark:bg-slate-900 flex items-center justify-center">
                <p className="text-slate-500 dark:text-slate-400 tracking-wider uppercase">Се вчитува…</p>
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-white dark:bg-slate-900 transition-colors duration-300">
            <div className="py-8 max-w-7xl mx-auto sm:px-6 lg:px-8">
                <Alert message="Немате внесено доволно букви" isOpen={isNotEnoughLetters} variant="error" />
                <Alert message={rejection ?? ''} isOpen={rejection !== null} variant="error" />
                <Alert
                    message={`Изгубивте, бараниот збор е ${solution ?? ''}`}
                    isOpen={isGameLost}
                    variant="error"
                />
                <Alert message="Копирано во clipboard за споделување" isOpen={shareComplete} variant="success" />

                {/* Header - Title left, buttons right */}
                <header className="flex items-center justify-between mb-2 mx-auto w-[300px]">
                    {/* Left: Title */}
                    <h1 className="text-3xl text-slate-800 dark:text-slate-100 tracking-wider uppercase font-bold">
                        Зборле
                    </h1>

                    {/* Right: Buttons group */}
                    <div className="flex items-center gap-1 bg-slate-100 dark:bg-slate-800 rounded-xl px-2 py-1.5">
                        <button
                            onClick={() => setIsInfoModalOpen(true)}
                            className="p-2 rounded-lg transition-all duration-200 hover:bg-slate-200 dark:hover:bg-slate-700 hover:scale-105 active:scale-95 focus:outline-none focus:ring-2 focus:ring-slate-400"
                            aria-label="Како се игра"
                            title="Помош"
                        >
                            <QuestionMarkCircleIcon className="h-5 w-5 text-slate-600 dark:text-slate-400" />
                        </button>
                        <div className="w-px h-4 bg-slate-300 dark:bg-slate-600" />
                        <button
                            onClick={() => setIsStatsModalOpen(true)}
                            className="p-2 rounded-lg transition-all duration-200 hover:bg-slate-200 dark:hover:bg-slate-700 hover:scale-105 active:scale-95 focus:outline-none focus:ring-2 focus:ring-slate-400"
                            aria-label="Статистика"
                            title="Статистика"
                        >
                            <ChartBarIcon className="h-5 w-5 text-slate-600 dark:text-slate-400" />
                        </button>
                    </div>
                </header>

                <Grid
                    guesses={guesses}
                    currentGuess={currentGuess}
                    invalid={isNotEnoughLetters || rejection !== null}
                    win={isWinAnimationStarted}
                />
                <Keyboard onChar={onChar} onDelete={onDelete} onEnter={() => void onEnter()} guesses={guesses} />
                <WinModal
                    isOpen={isWinModalOpen}
                    handleClose={() => setIsWinModalOpen(false)}
                    guesses={guesses}
                    handleShare={() => {
                        setIsWinModalOpen(false)
                        setShareComplete(true)
                        return setTimeout(() => {
                            setShareComplete(false)
                        }, ALERT_MS)
                    }}
                    timeLeft={timeUntilNextWord}
                />
                <InfoModal isOpen={isInfoModalOpen} handleClose={() => setIsInfoModalOpen(false)} />
                <StatsModal
                    isOpen={isStatsModalOpen}
                    handleClose={() => setIsStatsModalOpen(false)}
                    gameStats={stats}
                />
                <AboutModal isOpen={isAboutModalOpen} handleClose={() => setIsAboutModalOpen(false)} />
                <ShortcutsModal isOpen={isShortcutsModalOpen} handleClose={() => setIsShortcutsModalOpen(false)} />

                {/* Footer with Settings */}
                <footer className="mt-8 flex items-center justify-center">
                    <div className="flex items-center gap-1 px-3 py-2 bg-slate-100 dark:bg-slate-800 rounded-xl">
                        <SoundToggle />
                        <div className="w-px h-5 bg-slate-300 dark:bg-slate-600 mx-1" />
                        <ThemeToggle />
                        <div className="w-px h-5 bg-slate-300 dark:bg-slate-600 mx-1" />
                        <button
                            type="button"
                            className="p-2 rounded-lg transition-all duration-200 hover:bg-slate-200 dark:hover:bg-slate-700 hover:scale-105 active:scale-95 focus:outline-none focus:ring-2 focus:ring-slate-400"
                            onClick={() => setIsAboutModalOpen(true)}
                            aria-label="За играта"
                            title="За играта"
                        >
                            <InformationCircleIcon className="h-6 w-6 text-slate-700 dark:text-slate-300" />
                        </button>
                    </div>
                </footer>
            </div>
        </div>
    )
}

export default App
