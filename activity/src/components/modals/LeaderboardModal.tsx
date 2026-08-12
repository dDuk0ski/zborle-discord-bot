import { Fragment } from 'react'
import { Dialog, DialogTitle, Transition, TransitionChild } from '@headlessui/react'
import { XMarkIcon } from '@heroicons/react/24/outline'
import { LeaderboardRow } from '../../lib/api'

type Props = {
    isOpen: boolean
    handleClose: () => void
    rows: LeaderboardRow[]
    scope: 'guild' | 'dm'
    loading: boolean
    currentUserId: string | null
}

const MEDALS = ['🥇', '🥈', '🥉']

export const LeaderboardModal = ({ isOpen, handleClose, rows, scope, loading, currentUserId }: Props) => {
    return (
        <Transition show={isOpen} as={Fragment}>
            <Dialog as="div" className="fixed z-10 inset-0 overflow-y-auto" onClose={handleClose}>
                <div className="flex items-end justify-center min-h-screen pt-4 px-4 pb-20 text-center sm:block sm:p-0">
                    <TransitionChild
                        as={Fragment}
                        enter="ease-out duration-300"
                        enterFrom="opacity-0"
                        enterTo="opacity-100"
                        leave="ease-in duration-200"
                        leaveFrom="opacity-100"
                        leaveTo="opacity-0"
                    >
                        <div className="fixed inset-0 bg-gray-500 dark:bg-black bg-opacity-75 dark:bg-opacity-70 transition-opacity" />
                    </TransitionChild>

                    <span className="hidden sm:inline-block sm:align-middle sm:h-screen" aria-hidden="true">
                        &#8203;
                    </span>
                    <TransitionChild
                        as={Fragment}
                        enter="ease-out duration-300"
                        enterFrom="opacity-0 translate-y-4 sm:translate-y-0 sm:scale-95"
                        enterTo="opacity-100 translate-y-0 sm:scale-100"
                        leave="ease-in duration-200"
                        leaveFrom="opacity-100 translate-y-0 sm:scale-100"
                        leaveTo="opacity-0 translate-y-4 sm:translate-y-0 sm:scale-95"
                    >
                        <div className="inline-block align-bottom bg-white dark:bg-slate-800 rounded-lg px-4 pt-5 pb-4 text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-md sm:w-full sm:p-6">
                            <div className="absolute right-4 top-4">
                                <button
                                    onClick={handleClose}
                                    className="p-1 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
                                    aria-label="Затвори"
                                >
                                    <XMarkIcon className="h-6 w-6 text-slate-500 dark:text-slate-400" />
                                </button>
                            </div>

                            <DialogTitle
                                as="h3"
                                className="text-lg leading-6 font-bold text-slate-900 dark:text-slate-100 uppercase text-center"
                            >
                                Ранг-листа
                            </DialogTitle>

                            <div className="mt-4">
                                {loading ? (
                                    <p className="text-center text-slate-500 dark:text-slate-400 py-6">
                                        Се вчитува…
                                    </p>
                                ) : scope === 'dm' ? (
                                    <p className="text-center text-slate-500 dark:text-slate-400 py-6">
                                        Ранг-листата постои само на сервер. Твојата статистика сепак се брои.
                                    </p>
                                ) : rows.length === 0 ? (
                                    <p className="text-center text-slate-500 dark:text-slate-400 py-6">
                                        Никој сè уште нема завршена игра на овој сервер.
                                    </p>
                                ) : (
                                    <div className="overflow-x-auto">
                                        <table className="w-full text-sm">
                                            <thead>
                                                <tr className="text-slate-500 dark:text-slate-400 text-xs uppercase">
                                                    <th className="text-left font-semibold py-2 pr-2">Играч</th>
                                                    <th className="text-right font-semibold py-2 px-1.5">Победи</th>
                                                    <th className="text-right font-semibold py-2 px-1.5">Серија</th>
                                                    <th className="text-right font-semibold py-2 pl-1.5">Просек</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {rows.map((row, index) => (
                                                    <tr
                                                        key={row.userId}
                                                        className={
                                                            row.userId === currentUserId
                                                                ? 'bg-slate-100 dark:bg-slate-700/50'
                                                                : ''
                                                        }
                                                    >
                                                        <td className="py-2 pr-2">
                                                            <div className="flex items-center gap-2 min-w-0">
                                                                <span className="w-5 shrink-0 text-slate-400 tabular-nums">
                                                                    {MEDALS[index] ?? index + 1}
                                                                </span>
                                                                {row.avatarUrl && (
                                                                    <img
                                                                        src={row.avatarUrl}
                                                                        alt=""
                                                                        className="h-6 w-6 rounded-full shrink-0"
                                                                    />
                                                                )}
                                                                <span className="truncate text-slate-800 dark:text-slate-100">
                                                                    {row.displayName}
                                                                </span>
                                                            </div>
                                                        </td>
                                                        <td className="text-right tabular-nums py-2 px-1.5 text-slate-800 dark:text-slate-100">
                                                            {row.won}
                                                            <span className="text-slate-400">/{row.played}</span>
                                                        </td>
                                                        <td className="text-right tabular-nums py-2 px-1.5 text-slate-800 dark:text-slate-100">
                                                            {row.currentStreak}
                                                        </td>
                                                        <td className="text-right tabular-nums py-2 pl-1.5 text-slate-800 dark:text-slate-100">
                                                            {row.averageGuesses ?? '—'}
                                                        </td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                )}
                            </div>
                        </div>
                    </TransitionChild>
                </div>
            </Dialog>
        </Transition>
    )
}
