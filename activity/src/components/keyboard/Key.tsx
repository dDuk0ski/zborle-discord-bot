import { ReactNode } from 'react'
import classnames from 'classnames'
import { KeyValue } from '../../lib/keyboard'
import { CharStatus } from '../../lib/statuses'

type Props = {
    children?: ReactNode
    value: KeyValue
    width?: number
    status?: CharStatus
    onClick: (value: KeyValue) => void
}

export const Key = ({ children, status, width = 40, value, onClick }: Props) => {
    const isEnter = value === 'ENTER'
    const classes = classnames(
        // flex-1 with min-w-0 lets keys shrink to fit narrow screens. The Macedonian
        // keyboard has 13 keys in its top row against English Wordle's 10, so at the
        // fixed 40px width that row was 572px and overflowed every phone.
        'flex flex-1 min-w-0 items-center justify-center rounded mx-0.5 font-bold cursor-pointer transition-all duration-150 select-none h-12 sm:h-[58px]',
        {
            // Font size - smaller for ENTER, and smaller again on phones.
            'text-[10px] sm:text-sm': isEnter,
            'text-base sm:text-lg': !isEnter,
            // Default state
            'bg-slate-200 dark:bg-slate-700 hover:bg-slate-300 dark:hover:bg-slate-600 active:bg-slate-400 dark:active:bg-slate-500 text-slate-800 dark:text-slate-200':
                !status,
            // Absent state
            'bg-slate-500 dark:bg-slate-600 text-white': status === 'absent',
            // Correct state
            'bg-green-500 dark:bg-green-600 hover:bg-green-600 dark:hover:bg-green-700 active:bg-green-700 dark:active:bg-green-800 text-white':
                status === 'correct',
            // Present state
            'bg-yellow-500 dark:bg-yellow-600 hover:bg-yellow-600 dark:hover:bg-yellow-700 active:bg-yellow-700 dark:active:bg-yellow-800 text-white':
                status === 'present',
        },
    )

    return (
        // maxWidth keeps the original desktop proportions; flex-1 handles everything
        // narrower, so the same markup serves phones without a separate layout.
        <div
            style={{ maxWidth: `${width}px` }}
            className={classes}
            onClick={() => onClick(value)}
            role="button"
            tabIndex={0}
            onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    onClick(value)
                }
            }}
        >
            {children || value}
        </div>
    )
}
