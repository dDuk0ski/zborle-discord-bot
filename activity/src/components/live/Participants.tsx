import { Participant } from '../../lib/live'
import { MAX_GUESSES } from '../../lib/constants'

type Props = {
    players: Participant[]
    currentUserId: string | null
}

/**
 * Everyone else's progress in this session.
 *
 * Shows how far each player has got and the colour of their last row, which is enough
 * to feel the race without revealing anything about the word itself.
 */
export const Participants = ({ players, currentUserId }: Props) => {
    const others = players.filter((player) => player.userId !== currentUserId)
    if (others.length === 0) {
        return null
    }

    return (
        <div className="mx-auto w-[300px] mt-4 flex flex-col gap-2">
            {others.map((player) => (
                <div key={player.userId} className="flex items-center gap-2">
                    {player.avatarUrl ? (
                        <img src={player.avatarUrl} alt="" className="h-6 w-6 rounded-full shrink-0" />
                    ) : (
                        <div className="h-6 w-6 rounded-full bg-slate-300 dark:bg-slate-600 shrink-0" />
                    )}
                    <span className="text-xs text-slate-600 dark:text-slate-400 truncate flex-1 min-w-0">
                        {player.displayName}
                    </span>
                    <div className="flex gap-0.5 shrink-0" aria-label={`${player.guessCount}/${MAX_GUESSES}`}>
                        {Array.from({ length: MAX_GUESSES }).map((_, index) => {
                            const played = index < player.guessCount
                            const isLast = index === player.guessCount - 1
                            return (
                                <span
                                    key={index}
                                    className={[
                                        'h-2 w-3 rounded-sm transition-colors',
                                        !played
                                            ? 'bg-slate-200 dark:bg-slate-700'
                                            : player.isWon && isLast
                                              ? 'bg-green-500'
                                              : 'bg-slate-400 dark:bg-slate-500',
                                    ].join(' ')}
                                />
                            )
                        })}
                    </div>
                    {player.isWon && <span className="text-xs shrink-0">🎉</span>}
                    {player.isLost && <span className="text-xs shrink-0">😔</span>}
                </div>
            ))}
        </div>
    )
}
