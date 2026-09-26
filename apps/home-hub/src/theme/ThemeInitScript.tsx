import { DEFAULT_THEME_ID } from './types';
import { OLIN_THEMES } from './registry';

// Minified synchronous script to apply the theme attribute to the <html> tag
// before the browser paints. This prevents the "flash of wrong theme".
//
export const ThemeInitScript = ({ nonce }: { nonce?: string }) => {
  const code = `
    (function() {
      try {
        var validThemes = ${JSON.stringify(Object.keys(OLIN_THEMES))};
        var defaultTheme = '${DEFAULT_THEME_ID}';
        var stored = localStorage.getItem('olin.appearance.theme.v1');
        var theme = (stored && validThemes.indexOf(stored) !== -1) ? stored : defaultTheme;
        document.documentElement.setAttribute('data-olin-theme', theme);
      } catch (e) {
        document.documentElement.setAttribute('data-olin-theme', '${DEFAULT_THEME_ID}');
      }
    })();
  `;
  return <script nonce={nonce} dangerouslySetInnerHTML={{ __html: code }} />;
};
