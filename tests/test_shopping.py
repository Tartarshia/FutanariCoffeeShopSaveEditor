"""Synthetic shop catalogues; classification is never inferred from item type."""
import unittest
from unittest.mock import patch
import game_data
import model


def catalogue():
    def item(key, typ='Furniture', addable=True):
        return {'id':key,'name':key,'description':'fixture','type':typ,'group':typ,
                'addable':addable,'stack':9,'price':10,'sell':5}
    return {'items':{key:item(key, 'Clothes' if key=='shirt' else 'Furniture')
                     for key in ['chair','shirt','unlisted','both','banned_mission']},
            'missions':{'one':{'FurnitureShopItems':'chair,both,\\nchair',
                              'ClothesShopItems':'shirt','DarkShopItems':'both,missing'},
                        'two':{'FurnitureShopItems':'banned_mission','IsBanned':'TRUE'}}}


class ShoppingTests(unittest.TestCase):
    def test_real_shop_lists_multiple_sources_and_unknown(self):
        cat=catalogue()
        items=game_data.shopping_items(cat)
        self.assertEqual(items['chair']['sources'],['Furniture'])
        self.assertEqual(items['shirt']['sources'],['Clothes'])
        self.assertEqual(items['both']['sources'],['Furniture','DarkMerchant'])
        self.assertEqual(items['unlisted']['sources'],[])
        self.assertEqual(items['banned_mission']['sources'],[])
        self.assertNotIn('sources',cat['items']['chair'])

    def test_filters_counts_search_and_pagination(self):
        cat=catalogue()
        with patch('codec.catalogue',return_value=cat):
            d=model.catalogue_page('fixture',source='DarkMerchant')
            self.assertEqual([v['id'] for v in d['entries']],['both'])
            self.assertEqual(d['source_counts']['Furniture'],2)
            self.assertEqual(d['source_counts']['other'],2)
            self.assertEqual(model.catalogue_page('fixture',kind='Clothes')['count'],1)
            self.assertEqual(model.catalogue_page('fixture',source='Furniture',kind='Clothes')['count'],0)
            self.assertEqual(model.catalogue_page('fixture',query='CHA')['entries'][0]['id'],'chair')
            self.assertEqual(model.catalogue_page('fixture',source='other')['count'],2)
            self.assertEqual(model.catalogue_page('fixture',page=1)['entries'],[])
            for args in ({'source':'made_up'}, {'sort':'bad'}, {'kind':'bad'}, {'page':-1}):
                with self.subTest(args=args),self.assertRaises(ValueError):
                    model.catalogue_page('fixture',**args)

    def test_pagination_occurs_after_filtering_and_sorting(self):
        cat=catalogue()
        for i in range(35):
            cat['items'][f'fixture_{i:02}']={**cat['items']['chair'],'id':f'fixture_{i:02}','name':f'fixture_{i:02}'}
        cat['missions']['more']={'DarkShopItems':','.join(f'fixture_{i:02}' for i in range(35))}
        with patch('codec.catalogue',return_value=cat):
            first=model.catalogue_page('fixture',query='fixture',source='DarkMerchant',sort='id')
            second=model.catalogue_page('fixture',query='fixture',page=1,source='DarkMerchant',sort='id')
        self.assertEqual(first['count'],35)
        self.assertEqual(len(first['entries']),25)
        self.assertEqual(len(second['entries']),10)
        self.assertEqual(second['entries'][0]['id'],'fixture_25')
