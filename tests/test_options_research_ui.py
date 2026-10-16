import unittest
from pathlib import Path

class OptionsResearchUITests(unittest.TestCase):
    def test_readonly_tab_has_required_sections(self):
        text=Path('web/options-research.js').read_text(encoding='utf-8')
        for phrase in ('Options Research','META LIVE','TTT / Hysteresis','META ALPACA','Broker equity','Options BP','Daily halt','Posición actual','Último trade','ACCEPT / WAIT / BLOCK','Resultados por estrategia','Jev frente a Options Research','Resultados por activo','Coincidencias por señal','H09 PUT','Resultados por confianza Jev','/api/options-research','broker actions OFF','Cadena operativa','Ver todas las decisiones Meta','Ver todos los episodios TTT','historial detallado','P&L total','P&L/entrada','Base'):
            self.assertIn(phrase,text)
        self.assertNotIn('Ejecutar',text)
        self.assertLess(text.index('META ALPACA'),text.index('META LIVE'))
        self.assertIn('/options-research.js',Path('web/index.html').read_text(encoding='utf-8'))

if __name__=='__main__': unittest.main()
