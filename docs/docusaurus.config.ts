import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';
import {themes as prismThemes} from 'prism-react-renderer';

/**
 * The CDM documentation site.
 *
 * Docs-only: `routeBasePath: '/'` puts the Introduction at the site root, because everything
 * here IS documentation and a separate marketing landing page would be a second place to
 * state the contract. The blog preset is off for the same reason.
 *
 * Branding is a PLACEHOLDER — the product name and nothing else. No logo, no colours borrowed
 * from anywhere, no social card: an invented visual identity is harder to remove later than
 * it is to add now, and this repository is public.
 */
const config: Config = {
  title: 'SynapseCommand',
  tagline: 'Canonical Data Model, JSON Schema and adapter SDK',
  favicon: 'img/favicon.ico',

  // The custom domain the docs are served on. `url` feeds absolute links only — the sitemap,
  // canonical tags, og tags — so it does not affect navigation, which is exactly why a wrong
  // value here is worth fixing deliberately: nothing breaks visibly, and every crawler and
  // every shared link points somewhere that is not the site.
  url: 'https://docs.synapsecommand.com',
  baseUrl: '/',

  // A broken link in a contract reference is a wrong contract, so it fails the build rather
  // than warning. Anchors are only warned about: they resolve against rendered headings, and
  // the generated pages create their anchors from schema `$defs` names.
  onBrokenLinks: 'throw',
  onBrokenAnchors: 'warn',

  markdown: {
    hooks: {
      // Moved here from the deprecated top-level `onBrokenMarkdownLinks` (removed in v4).
      onBrokenMarkdownLinks: 'throw',
    },
  },

  future: {
    // Rspack + SWC (`faster`, renamed from `experimental_faster` in 3.9). Opt-in, and the
    // reason the build stays quick enough to run on every push.
    v4: true,
    faster: true,
  },

  presets: [
    [
      'classic',
      {
        docs: {
          routeBasePath: '/',
          sidebarPath: './sidebars.ts',
          // Every page carries an "edit this page" link to the file that produced it, which
          // for the generated reference points at the generator's output — deliberately, so
          // a reader who spots a wrong field lands on the file that says DO NOT EDIT and
          // reads why.
          editUrl:
            'https://github.com/Decent-Cybersecurity/synapsecommand-public/tree/main/docs/',
          showLastUpdateTime: true,
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
        sitemap: {
          lastmod: 'date',
          changefreq: null,
          priority: null,
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    colorMode: {
      // Dark by default, and the toggle is kept: a reader on a bright screen must be able to
      // switch. `respectPrefersColorScheme: false` is what makes "default dark" actually
      // mean dark rather than "whatever the OS says", which is the setting that gets asked
      // for and then silently not applied.
      defaultMode: 'dark',
      respectPrefersColorScheme: false,
      disableSwitch: false,
    },
    navbar: {
      title: 'SynapseCommand',
      hideOnScroll: false,
      items: [
        {type: 'docSidebar', sidebarId: 'cdmSidebar', position: 'left', label: 'Documentation'},
        {
          href: 'https://github.com/Decent-Cybersecurity/synapsecommand-public',
          label: 'Repository',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Contract',
          items: [
            {label: 'Canonical Data Model', to: '/cdm/entity'},
            {label: 'JSON Schema Reference', to: '/schema-reference/'},
            {label: 'Changelog', to: '/changelog'},
          ],
        },
        {
          title: 'Building on it',
          items: [
            {label: 'Writing an Adapter', to: '/writing-an-adapter'},
            {
              label: 'Repository',
              href: 'https://github.com/Decent-Cybersecurity/synapsecommand-public',
            },
          ],
        },
      ],
      copyright: 'SynapseCommand · Apache-2.0',
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      // `python` and `xml` are not in the default Prism bundle and the adapter pages are
      // mostly those two. `bash` and `json` come for free but are listed for the record.
      additionalLanguages: ['python', 'bash', 'json', 'markup', 'yaml', 'diff'],
    },
    tableOfContents: {
      minHeadingLevel: 2,
      maxHeadingLevel: 3,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
