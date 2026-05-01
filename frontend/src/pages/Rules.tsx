import React from 'react';
import { Link } from 'react-router-dom';

export default function RulesPage() {
  const sections = [
    {
      title: 'Team Selection',
      rules: [
        'Select exactly 11 players per match',
        'At least 1 player from each role (WK, BAT, AR, BWL)',
        'Choose 1 Captain (2x points) and 1 Vice Captain (1.5x points)',
        'Team locks at match start time - no changes after',
      ],
    },
    {
      title: 'Batting Points',
      rules: [
        'Playing in match: +4 pts',
        'Runs scored: +1 per run',
        'Fours: +4 per boundary',
        'Sixes: +6 per six',
        '30 runs: +4 bonus',
        '50 runs: +8 bonus',
        '75 runs: +12 bonus',
        '100 runs: +16 bonus',
        'Duck (out for 0): -2 pts (WK/BAT/AR only)',
      ],
    },
    {
      title: 'Strike Rate (min 10 balls, WK/BAT/AR only)',
      rules: [
        'SR > 170: +6 pts',
        'SR > 150: +4 pts',
        'SR >= 130: +2 pts',
        'SR <= 70: -2 pts',
        'SR < 60: -4 pts',
        'SR <= 50: -6 pts',
      ],
    },
    {
      title: 'Bowling Points',
      rules: [
        'Wickets: +30 per wicket',
        'Bowled/LBW dismissal: +8 pts',
        '3 wickets: +4 bonus',
        '4 wickets: +8 bonus',
        '5 wickets: +16 bonus',
        'Maiden over: +12 pts',
        'Dot balls: +1 per dot ball',
      ],
    },
    {
      title: 'Economy Rate (min 2 overs)',
      rules: [
        'Economy < 5: +6 pts',
        'Economy < 6: +4 pts',
        'Economy <= 7: +2 pts',
        'Economy >= 10: -2 pts',
        'Economy > 11: -4 pts',
        'Economy > 12: -6 pts',
      ],
    },
    {
      title: 'Fielding Points',
      rules: [
        'Catch: +8 per catch',
        '3+ catches: +4 bonus',
        'Stumping: +12 pts',
        'Direct run out: +12 pts',
        'Indirect run out: +6 pts (shared)',
      ],
    },
    {
      title: 'Captain & Vice Captain',
      rules: [
        'Captain (C): All points × 2',
        'Vice Captain (VC): All points × 1.5',
        'Other players: Points × 1',
      ],
    },
    {
      title: 'Prize Pool',
      rules: [
        'Entry fee: ₹50 per match per participant',
        'Prize pool = Total participants × ₹50',
        '1st place: 50% of prize pool',
        '2nd place: 30% of prize pool',
        '3rd place: 20% of prize pool',
      ],
    },
  ];

  return (
    <div>
      <div className="mb-4">
        <Link
          to="/"
          className="inline-flex items-center gap-2 px-3 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-sm text-white/90"
        >
          ← Back to Dashboard
        </Link>
      </div>

      <h2 className="text-xl font-bold text-white mb-6">Scoring Rules</h2>

      <div className="grid gap-6">
        {sections.map((s) => (
          <section key={s.title} className="bg-white/3 p-4 rounded-lg">
            <h3 className="font-semibold text-white mb-2">{s.title}</h3>
            <ul className="list-disc list-inside text-sm text-white/80">
              {s.rules.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
