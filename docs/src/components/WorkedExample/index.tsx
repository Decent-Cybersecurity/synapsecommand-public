import React from 'react';
import CodeBlock from '@theme/CodeBlock';

import example from '@site/src/data/worked-example.json';
import styles from './styles.module.css';

/**
 * The worked example: one real PNTMAP fixture beside the real golden output it produces.
 *
 * Both sides are read from the repository at generate time (see
 * `docs/scripts/lib/schema-to-mdx.mjs`) and written into `src/data/worked-example.json`, which
 * the drift check covers. Nothing on this page is transcribed by hand — a hand-copied excerpt
 * of a golden file is a claim about the adapter that no test checks, and it is exactly the kind
 * of claim that stays on a page for a year after the adapter changed.
 *
 * Side by side on a wide screen, stacked on a narrow one. Each column scrolls independently:
 * the golden output is legitimately four times the size of its input (one alert becomes an
 * entity and an event, both fully provenanced), so locking the two columns to one height would
 * make the shorter one mostly whitespace.
 */
export default function WorkedExample(): React.ReactElement {
  return (
    <div className={styles.wrapper}>
      <div className={styles.column}>
        <div className={styles.heading}>
          <span className={styles.badgeIn}>input</span>
          <code className={styles.path}>{example.fixture}</code>
        </div>
        <CodeBlock language="json" className={styles.code}>
          {example.source}
        </CodeBlock>
      </div>

      <div className={styles.arrow} aria-hidden="true">
        →
      </div>

      <div className={styles.column}>
        <div className={styles.heading}>
          <span className={styles.badgeOut}>golden output</span>
          <code className={styles.path}>{example.golden}</code>
        </div>
        <CodeBlock language="json" className={styles.code}>
          {example.output}
        </CodeBlock>
      </div>
    </div>
  );
}

/**
 * The provenance line for the pair, so a reader can verify the page against the repository
 * without trusting the page. Rendered separately from the columns because it belongs to the
 * claim ("these are those files"), not to either side of it.
 */
export function WorkedExampleProvenance(): React.ReactElement {
  return (
    <table className={styles.provenance}>
      <thead>
        <tr>
          <th>File</th>
          <th>SHA-256</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>
            <code>{example.fixture}</code>
          </td>
          <td>
            <code>{example.sourceSha256}</code>
          </td>
        </tr>
        <tr>
          <td>
            <code>{example.golden}</code>
          </td>
          <td>
            <code>{example.goldenSha256}</code>
          </td>
        </tr>
      </tbody>
    </table>
  );
}
