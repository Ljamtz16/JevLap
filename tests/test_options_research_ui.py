import unittest
from pathlib import Path

class OptionsResearchUITests(unittest.TestCase):
    def test_readonly_tab_has_required_sections(self):
        text=Path('web/options-research.js').read_text(encoding='utf-8')
        for phrase in ('Options Research','Resultados por estrategia','Jev frente a Options Research','Resultados por activo','Coincidencias por señal','H09 PUT','Resultados por confianza Jev','/api/options-research','broker actions OFF'):
            self.assertIn(phrase,text)
        self.assertNotIn('Ejecutar',text)
        self.assertIn('/options-research.js',Path('web/index.html').read_text(encoding='utf-8'))

if __name__=='__main__': unittest.main()
