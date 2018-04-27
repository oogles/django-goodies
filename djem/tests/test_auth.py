from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import AnonymousUser, Group, Permission, User
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import Http404, HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.views import View

from djem.auth import ObjectPermissionsBackend, PermissionRequiredMixin, permission_required

from .models import CustomUser, OLPTest, UniversalOLPTest


def _test_view(request, obj=None):
    
    return HttpResponse('success')


class _TestView(PermissionRequiredMixin, View):
    
    def get(self, *args, **kwargs):
        
        return HttpResponse('success')


@override_settings(AUTH_USER_MODEL='auth.User')
class OLPTestCase(TestCase):
    
    UserModel = User
    TestModel = OLPTest
    model_name = 'olptest'
    
    def setUp(self):
        
        group1 = Group.objects.create(name='Test Group 1')
        group2 = Group.objects.create(name='Test Group 2')
        
        user1 = self.UserModel.objects.create_user('test1')
        user1.groups.add(group1)
        
        user2 = self.UserModel.objects.create_user('test2')
        user2.groups.add(group2)
        
        # Grant both users and both groups all permissions for OLPTest, at
        # the model level (except "closed", only accessible to super users)
        permissions = Permission.objects.filter(
            content_type__app_label='tests',
            content_type__model=self.model_name
        ).exclude(codename='closed_{0}'.format(self.model_name))
        
        user1.user_permissions.set(permissions)
        user2.user_permissions.set(permissions)
        group1.permissions.set(permissions)
        group2.permissions.set(permissions)
        
        self.user1 = user1
        self.user2 = user2
        self.group1 = group1
        self.group2 = group2
        self.all_permissions = permissions
    
    def perm(self, perm_name):
        
        return 'tests.{0}_{1}'.format(perm_name, self.model_name)
    
    def cache(self, cache_type, perm_name, obj):
        
        return '_{0}_perm_cache_tests.{1}_{2}_{3}'.format(
            cache_type,
            perm_name,
            self.model_name,
            obj.pk
        )
    
    def test_auth__valid(self):
        """
        Test the backend does not interfere with valid user authentication.
        """
        
        user = self.user1
        user.set_password('blahblahblah')
        user.save()
        
        self.assertTrue(authenticate(username='test1', password='blahblahblah'))
    
    def test_auth__invalid(self):
        """
        Test the backend does not interfere with invalid user authentication.
        """
        
        self.assertFalse(authenticate(username='test1', password='badpassword'))
    
    def test_has_perm__no_model_level(self):
        """
        Test a user is denied object-level permissions if they don't have the
        corresponding model-level permissions.
        """
        
        obj = self.TestModel.objects.create()
        
        user1 = self.UserModel.objects.create_user('useless')
        perm1 = user1.has_perm(self.perm('open'), obj)
        self.assertFalse(perm1)
        
        user2 = self.UserModel.objects.create_user('useful')
        user2.user_permissions.add(Permission.objects.get(codename='open_{0}'.format(self.model_name)))
        perm2 = user2.has_perm(self.perm('open'), obj)
        self.assertTrue(perm2)
    
    def test_has_perm__inactive_user(self):
        """
        Test an inactive user is denied object-level permissions without ever
        reaching the object's permission access method.
        """
        
        user = self.UserModel.objects.create_user('inactive')
        user.is_active = False
        user.save()
        
        # Grant the user the "open" permission to ensure it is their
        # inactive-ness that denies them permission
        user.user_permissions.add(Permission.objects.get(codename='open_{0}'.format(self.model_name)))
        
        obj = self.TestModel.objects.create()
        
        perm = user.has_perm(self.perm('open'), obj)
        
        self.assertFalse(perm)
    
    def test_has_perm__super_user(self):
        """
        Test a superuser is granted object-level permissions without ever
        reaching the object's permission access method.
        """
        
        user = self.UserModel.objects.create_user('super')
        user.is_superuser = True
        user.save()
        
        # Deliberately do not grant the user the "open" permission to
        # ensure it is their super-ness that grants them permission
        
        obj = self.TestModel.objects.create()
        
        perm = user.has_perm(self.perm('open'), obj)
        
        self.assertTrue(perm)
    
    def test_has_perm__inactive_super_user(self):
        """
        Test an inactive superuser is denied object-level permissions without
        ever reaching the object's permission access method, despite being a
        superuser.
        """
        
        user = self.UserModel.objects.create_user('superinactive')
        user.is_superuser = True
        user.is_active = False
        user.save()
        
        # Grant the user the "open" permission to ensure it is their
        # inactive-ness that denies them permission
        user.user_permissions.add(Permission.objects.get(codename='open_{0}'.format(self.model_name)))
        
        obj = self.TestModel.objects.create()
        
        perm = user.has_perm(self.perm('open'), obj)
        
        self.assertFalse(perm)
    
    def test_has_perm__no_access_fn(self):
        """
        Test that the lack of defined permission access functions on the object
        being tested does not deny access (checking a permission without passing
        an object should be identical to checking a permission with passing an
        object, if there is no object-level logic involved in granting/denying
        the permission).
        """
        
        obj = self.TestModel.objects.create()
        
        # Test without object
        model_perm = self.user1.has_perm(self.perm('add'))
        self.assertTrue(model_perm)
        
        # Test with object
        obj_perm = self.user1.has_perm(self.perm('add'), obj)
        self.assertTrue(obj_perm)
    
    def test_has_perm__user_only_logic(self):
        """
        Test that an object's user-based permission access method can be used
        to grant permissions to some users and not others, when all users have
        the same permission at the model level, by returning True/False, and
        that the result is unaffected by having no group-based logic defined.
        """
        
        obj = self.TestModel.objects.create(user=self.user1)
        
        perm1 = self.user1.has_perm(self.perm('user_only'), obj)
        perm2 = self.user2.has_perm(self.perm('user_only'), obj)
        
        self.assertTrue(perm1)
        self.assertFalse(perm2)
    
    def test_has_perm__group_only_logic(self):
        """
        Test that an object's group-based permission access method can be used
        to grant permissions to some users and not others based on their
        groups, when all groups have the same permission at the model level, and
        that the result is unaffected by having no user-based logic defined.
        """
        
        obj = self.TestModel.objects.create(group=self.group1)
        
        perm1 = self.user1.has_perm(self.perm('group_only'), obj)
        perm2 = self.user2.has_perm(self.perm('group_only'), obj)
        
        self.assertTrue(perm1)
        self.assertFalse(perm2)
    
    def test_has_perm__combined_logic(self):
        """
        Test that an object's user-based AND group-based permission access
        methods can be used together to grant permissions to some users and not
        others, with either one able to grant the permission if the other does
        not.
        """
        
        obj1 = self.TestModel.objects.create(user=self.user1, group=self.group2)
        obj2 = self.TestModel.objects.create()
        
        # User = True, Group untested
        user_perm1 = self.user1.has_perm(self.perm('user_only'), obj1)
        group_perm1 = self.user1.has_perm(self.perm('group_only'), obj1)
        combined_perm1 = self.user1.has_perm(self.perm('combined'), obj1)
        self.assertTrue(user_perm1)
        self.assertFalse(group_perm1)
        self.assertTrue(combined_perm1)
        
        # User = False, Group = True
        user_perm2 = self.user2.has_perm(self.perm('user_only'), obj1)
        group_perm2 = self.user2.has_perm(self.perm('group_only'), obj1)
        combined_perm2 = self.user2.has_perm(self.perm('combined'), obj1)
        self.assertFalse(user_perm2)
        self.assertTrue(group_perm2)
        self.assertTrue(combined_perm2)
        
        # User = False, Group = False
        user_perm3 = self.user1.has_perm(self.perm('user_only'), obj2)
        group_perm3 = self.user1.has_perm(self.perm('group_only'), obj2)
        combined_perm3 = self.user1.has_perm(self.perm('combined'), obj2)
        self.assertFalse(user_perm3)
        self.assertFalse(group_perm3)
        self.assertFalse(combined_perm3)
    
    def test_has_perm__permissiondenied(self):
        """
        Test that an object's permission access methods can raise the
        PermissionDenied exception and have it treated as returning False.
        """
        
        obj = self.TestModel.objects.create(user=self.user1)
        
        perm = self.user1.has_perm(self.perm('deny'), obj)
        
        self.assertFalse(perm)
    
    def test_has_perm__cache(self):
        """
        Test that determining a user's object-level permission creates a cache
        on the User instance of the result, for the permission and object tested.
        """
        
        user = self.user1
        obj = self.TestModel.objects.create()
        user_perm_cache_name = self.cache('user', 'combined', obj)
        group_perm_cache_name = self.cache('group', 'combined', obj)
        
        # Test cache does not exist
        with self.assertRaises(AttributeError):
            getattr(user, user_perm_cache_name)
        
        with self.assertRaises(AttributeError):
            getattr(user, group_perm_cache_name)
        
        user.has_perm(self.perm('combined'), obj)
        
        # Test cache has been set
        self.assertFalse(getattr(user, user_perm_cache_name))
        self.assertFalse(getattr(user, group_perm_cache_name))
        
        # Test requerying for the user resets the cache
        user = self.UserModel.objects.get(pk=user.pk)
        
        with self.assertRaises(AttributeError):
            getattr(user, user_perm_cache_name)
        
        with self.assertRaises(AttributeError):
            getattr(user, group_perm_cache_name)
    
    def test_has_perms(self):
        """
        Test PermissionsMixin.has_perms works and correctly identifies the
        object-level permissions the user has.
        """
        
        obj = self.TestModel.objects.create(user=self.user1)
        
        perm1 = self.user1.has_perms((self.perm('open'), self.perm('combined')), obj)
        self.assertTrue(perm1)
        
        perm2 = self.user2.has_perms((self.perm('open'), self.perm('combined')), obj)
        self.assertFalse(perm2)
    
    def test_get_user_permissions(self):
        """
        Test ObjectPermissionsBackend.get_user_permissions() works and correctly
        identifies the object-level permissions the user has.
        Test the backend directly, without going through User/PermissionsMixin
        as they don't provide a mapping through to it.
        """
        
        backend = ObjectPermissionsBackend()
        obj = self.TestModel.objects.create(user=self.user1, group=self.group1)
        
        self.assertEqual(backend.get_user_permissions(self.user1, obj), {
            self.perm('delete'),
            self.perm('change'),
            self.perm('add'),
            self.perm('open'),
            self.perm('user_only'),
            self.perm('combined')
        })
        
        self.assertEqual(backend.get_user_permissions(self.user2, obj), {
            self.perm('delete'),
            self.perm('change'),
            self.perm('add'),
            self.perm('open')
        })
    
    def test_get_user_permissions__inactive_user(self):
        """
        Test ObjectPermissionsBackend.get_user_permissions() correctly denies
        all permissions to inactive users.
        Test the backend directly, without going through User/PermissionsMixin
        as they don't provide a mapping through to it.
        """
        
        backend = ObjectPermissionsBackend()
        user = self.UserModel.objects.create_user('inactive')
        user.is_active = False
        user.save()
        
        # Give the user all model-level permissions to ensure it is the
        # inactive-ness that denies them permission
        user.user_permissions.set(self.all_permissions)
        
        obj = self.TestModel.objects.create()
        
        perms = backend.get_user_permissions(user, obj)
        self.assertEqual(perms, set())
    
    def test_get_user_permissions__super_user(self):
        """
        Test ObjectPermissionsBackend.get_user_permissions() correctly grants
        all permissions to superusers.
        Test the backend directly, without going through User/PermissionsMixin
        as they don't provide a mapping through to it.
        """
        
        backend = ObjectPermissionsBackend()
        user = self.UserModel.objects.create_user('super')
        user.is_superuser = True
        user.save()
        
        # The user deliberately does not have any model-level permissions to
        # ensure it is the super-ness that grants them permission
        
        obj = self.TestModel.objects.create()
        
        perms = backend.get_user_permissions(user, obj)
        self.assertEqual(perms, {
            self.perm('delete'),
            self.perm('change'),
            self.perm('add'),
            self.perm('open'),
            self.perm('closed'),
            self.perm('user_only'),
            self.perm('group_only'),
            self.perm('combined'),
            self.perm('deny')
        })
    
    def test_get_user_permissions__inactive_super_user(self):
        """
        Test ObjectPermissionsBackend.get_user_permissions() correctly denies
        all permissions to inactive users, even superusers.
        Test the backend directly, without going through User/PermissionsMixin
        as they don't provide a mapping through to it.
        """
        
        backend = ObjectPermissionsBackend()
        user = self.UserModel.objects.create_user('superinactive')
        user.is_superuser = True
        user.is_active = False
        user.save()
        
        # Give the user all model-level permissions to ensure it is the
        # inactive-ness that denies them permission
        user.user_permissions.set(self.all_permissions)
        
        obj = self.TestModel.objects.create()
        
        perms = backend.get_user_permissions(user, obj)
        self.assertEqual(perms, set())
    
    def test_get_user_permissions__cache(self):
        """
        Test that PermissionsMixin.get_user_permissions correctly creates a
        a cache on the User instance of the result of each permission test, for
        the permission and object tested.
        """
        
        backend = ObjectPermissionsBackend()
        user = self.user1
        obj = self.TestModel.objects.create()
        
        expected_caches = (
            self.cache('user', 'add', obj),
            self.cache('user', 'change', obj),
            self.cache('user', 'delete', obj),
            self.cache('user', 'open', obj),
            self.cache('user', 'closed', obj),
            self.cache('user', 'user_only', obj),
            self.cache('user', 'group_only', obj),
            self.cache('user', 'combined', obj),
            self.cache('user', 'deny', obj)
        )
        
        # Test caches do not exist
        for cache_attr in expected_caches:
            with self.assertRaises(AttributeError):
                getattr(user, cache_attr)
        
        backend.get_user_permissions(user, obj)
        
        # Test caches have been set
        for cache_attr in expected_caches:
            try:
                getattr(user, cache_attr)
            except AttributeError:  # pragma: no cover
                self.fail('Cache not set: {0}'.format(cache_attr))
        
        # Test requerying for the user resets the cache
        user = self.UserModel.objects.get(pk=user.pk)
        for cache_attr in expected_caches:
            with self.assertRaises(AttributeError):
                getattr(user, cache_attr)
    
    def test_get_group_permissions(self):
        """
        Test PermissionsMixin.get_group_permissions() works and correctly
        identifies the object-level permissions the user has.
        """
        
        obj = self.TestModel.objects.create(user=self.user1, group=self.group1)
        
        self.assertEqual(self.user1.get_group_permissions(obj), {
            self.perm('delete'),
            self.perm('change'),
            self.perm('add'),
            self.perm('open'),
            self.perm('group_only'),
            self.perm('combined'),
            self.perm('deny')  # no group-based access method, defaults open
        })
        
        self.assertEqual(self.user2.get_group_permissions(obj), {
            self.perm('delete'),
            self.perm('change'),
            self.perm('add'),
            self.perm('open'),
            self.perm('deny')  # no group-based access method, defaults open
        })
    
    def test_get_group_permissions__inactive_user(self):
        """
        Test PermissionsMixin.get_group_permissions() correctly denies all
        permissions to inactive users.
        """
        
        user = self.UserModel.objects.create_user('inactive')
        user.is_active = False
        user.save()
        
        # Give the user all model-level permissions to ensure it is the
        # inactive-ness that denies them permission
        user.user_permissions.set(self.all_permissions)
        
        obj = self.TestModel.objects.create(user=user)
        
        perms = user.get_group_permissions(obj)
        self.assertEqual(perms, set())
    
    def test_get_group_permissions__super_user(self):
        """
        Test PermissionsMixin.get_group_permissions() correctly grants all
        permissions to superusers.
        """
        
        user = self.UserModel.objects.create_user('super')
        user.is_superuser = True
        user.save()
        
        # The user deliberately does not have any model-level permissions to
        # ensure it is the super-ness that grants them permission
        
        obj = self.TestModel.objects.create()
        
        self.assertEqual(user.get_all_permissions(obj), {
            self.perm('delete'),
            self.perm('change'),
            self.perm('add'),
            self.perm('open'),
            self.perm('closed'),
            self.perm('user_only'),
            self.perm('group_only'),
            self.perm('combined'),
            self.perm('deny')
        })
    
    def test_get_group_permissions__inactive_super_user(self):
        """
        Test PermissionsMixin.get_group_permissions() correctly denies all
        permissions to inactive users, even superusers.
        """
        
        user = self.UserModel.objects.create_user('superinactive')
        user.is_superuser = True
        user.is_active = False
        user.save()
        
        # Give the user all model-level permissions to ensure it is the
        # inactive-ness that denies them permission
        user.user_permissions.set(self.all_permissions)
        
        obj = self.TestModel.objects.create(user=user)
        
        perms = user.get_group_permissions(obj)
        self.assertEqual(perms, set())
    
    def test_get_group_permissions__cache(self):
        """
        Test that PermissionsMixin.get_group_permissions() correctly creates a
        a cache on the User instance of the result of each permission test, for
        the permission and object tested.
        """
        
        user = self.user1
        obj = self.TestModel.objects.create()
        
        expected_caches = (
            self.cache('group', 'add', obj),
            self.cache('group', 'change', obj),
            self.cache('group', 'delete', obj),
            self.cache('group', 'open', obj),
            self.cache('group', 'closed', obj),
            self.cache('group', 'user_only', obj),
            self.cache('group', 'group_only', obj),
            self.cache('group', 'combined', obj),
            self.cache('group', 'deny', obj)
        )
        
        # Test caches do not exist
        for cache_attr in expected_caches:
            with self.assertRaises(AttributeError):
                getattr(user, cache_attr)
        
        user.get_group_permissions(obj)
        
        # Test caches have been set
        for cache_attr in expected_caches:
            try:
                getattr(user, cache_attr)
            except AttributeError:  # pragma: no cover
                self.fail('Cache not set: {0}'.format(cache_attr))
        
        # Test requerying for the user resets the cache
        user = self.UserModel.objects.get(pk=user.pk)
        for cache_attr in expected_caches:
            with self.assertRaises(AttributeError):
                getattr(user, cache_attr)
    
    def test_get_all_permissions(self):
        """
        Test PermissionsMixin.get_all_permissions() works and correctly
        identifies the object-level permissions the user has.
        """
        
        obj = self.TestModel.objects.create(user=self.user1, group=self.group1)
        
        self.assertEqual(self.user1.get_all_permissions(obj), {
            self.perm('delete'),
            self.perm('change'),
            self.perm('add'),
            self.perm('open'),
            self.perm('user_only'),
            self.perm('group_only'),
            self.perm('combined')
        })
        
        self.assertEqual(self.user2.get_all_permissions(obj), {
            self.perm('delete'),
            self.perm('change'),
            self.perm('add'),
            self.perm('open')
        })
    
    def test_get_all_permissions__inactive_user(self):
        """
        Test PermissionsMixin.get_all_permissions() correctly denies all
        permissions to inactive users.
        """
        
        user = self.UserModel.objects.create_user('inactive')
        user.is_active = False
        user.save()
        
        # Give the user all model-level permissions to ensure it is the
        # inactive-ness that denies them permission
        user.user_permissions.set(self.all_permissions)
        
        obj = self.TestModel.objects.create(user=user)
        
        perms = user.get_all_permissions(obj)
        self.assertEqual(perms, set())
    
    def test_get_all_permissions__super_user(self):
        """
        Test PermissionsMixin.get_all_permissions() correctly grants all
        permissions to superusers.
        """
        
        user = self.UserModel.objects.create_user('super')
        user.is_superuser = True
        user.save()
        
        # The user deliberately does not have any model-level permissions to
        # ensure it is the super-ness that grants them permission
        
        obj = self.TestModel.objects.create()
        
        self.assertEqual(user.get_all_permissions(obj), {
            self.perm('delete'),
            self.perm('change'),
            self.perm('add'),
            self.perm('open'),
            self.perm('closed'),
            self.perm('user_only'),
            self.perm('group_only'),
            self.perm('combined'),
            self.perm('deny')
        })
    
    def test_get_all_permissions__inactive_super_user(self):
        """
        Test PermissionsMixin.get_all_permissions() correctly denies all
        permissions to inactive users, even superusers.
        """
        
        user = self.UserModel.objects.create_user('superinactive')
        user.is_superuser = True
        user.is_active = False
        user.save()
        
        # Give the user all model-level permissions to ensure it is the
        # inactive-ness that denies them permission
        user.user_permissions.set(self.all_permissions)
        
        obj = self.TestModel.objects.create(user=user)
        
        perms = user.get_all_permissions(obj)
        self.assertEqual(perms, set())
    
    def test_get_all_permissions__cache(self):
        """
        Test that PermissionsMixin.get_all_permissions() correctly creates a
        a cache on the User instance of the result of each permission test, for
        the permission and object tested.
        """
        
        user = self.user1
        obj = self.TestModel.objects.create(user=user)
        
        expected_caches = (
            self.cache('user', 'add', obj),
            self.cache('group', 'add', obj),
            
            self.cache('user', 'change', obj),
            self.cache('group', 'change', obj),
            
            self.cache('user', 'delete', obj),
            self.cache('group', 'delete', obj),
            
            self.cache('user', 'open', obj),  # group won't need checking
            
            self.cache('user', 'closed', obj),
            self.cache('group', 'closed', obj),
            
            self.cache('user', 'user_only', obj),  # group won't need checking
            
            self.cache('user', 'group_only', obj),
            self.cache('group', 'group_only', obj),
            
            self.cache('user', 'combined', obj),  # group won't need checking
            
            self.cache('user', 'deny', obj),
            self.cache('group', 'deny', obj)
        )
        
        expected_caches = [s.format(obj.pk) for s in expected_caches]
        
        unexpected_caches = (
            self.cache('group', 'open', obj),
            self.cache('group', 'user_only', obj),
            self.cache('group', 'combined', obj)
        )
        
        unexpected_caches = [s.format(obj.pk) for s in unexpected_caches]
        
        # Test all caches do not exist
        for cache_attr in expected_caches + unexpected_caches:
            with self.assertRaises(AttributeError):
                getattr(user, cache_attr)
        
        user.get_all_permissions(obj)
        
        # Test expected caches have been set
        for cache_attr in expected_caches:
            try:
                getattr(user, cache_attr)
            except AttributeError:  # pragma: no cover
                self.fail('Cache not set: {0}'.format(cache_attr))
        
        # Test unexpected caches still do not exist
        for cache_attr in unexpected_caches:
            with self.assertRaises(AttributeError):
                getattr(user, cache_attr)
        
        # Test requerying for the user resets the all caches
        user = self.UserModel.objects.get(pk=user.pk)
        for cache_attr in expected_caches + unexpected_caches:
            with self.assertRaises(AttributeError):
                getattr(user, cache_attr)


@override_settings(AUTH_USER_MODEL='tests.CustomUser', DJEM_UNIVERSAL_OLP=False)
class UniversalOLPFalseTestCase(OLPTestCase):
    
    #
    # A repeat of the object-level permissions tests for the default user model,
    # but for one incorporating OLPMixin, and with DJEM_UNIVERSAL_OLP=False.
    # Results should be identical.
    #
    
    UserModel = CustomUser
    TestModel = UniversalOLPTest
    model_name = 'universalolptest'


@override_settings(AUTH_USER_MODEL='tests.CustomUser', DJEM_UNIVERSAL_OLP=True)
class UniversalOLPTrueTestCase(OLPTestCase):
    
    #
    # A repeat of the object-level permissions tests for the default user model,
    # but for one incorporating OLPMixin, and with DJEM_UNIVERSAL_OLP=True.
    # Results should be identical EXCEPT for the tests involving active
    # superusers, which should actually perform object-level permissions rather
    # than unconditionally granting such users every permission.
    #
    
    UserModel = CustomUser
    TestModel = UniversalOLPTest
    model_name = 'universalolptest'
    
    def test_get_user_permissions__super_user(self):
        """
        Test ObjectPermissionsBackend.get_user_permissions() correctly subjects
        superusers to the same object-level permission logic as a standard user
        (they simply don't require the model-level permission be granted to
        them explicitly).
        Test the backend directly, without going through User/PermissionsMixin
        as they don't provide a mapping through to it.
        """
        
        backend = ObjectPermissionsBackend()
        user = self.UserModel.objects.create_user('super')
        user.is_superuser = True
        user.save()
        
        # The user deliberately does not have any model-level permissions to
        # ensure it is the super-ness that grants them model-level permission
        
        obj = self.TestModel.objects.create()
        
        perms = backend.get_user_permissions(user, obj)
        self.assertEqual(perms, {
            self.perm('delete'),
            self.perm('change'),
            self.perm('add'),
            self.perm('open'),
            self.perm('closed')
        })
    
    def test_get_group_permissions__super_user(self):
        """
        Test PermissionsMixin.get_group_permissions() correctly subjects
        superusers to the same object-level permission logic as a standard user
        (they simply don't require the model-level permission be granted to
        them explicitly).
        """
        
        user = self.UserModel.objects.create_user('super')
        user.is_superuser = True
        user.save()
        
        # The user deliberately does not have any model-level permissions to
        # ensure it is the super-ness that grants them model-level permission
        
        obj = self.TestModel.objects.create()
        
        self.assertEqual(user.get_all_permissions(obj), {
            self.perm('delete'),
            self.perm('change'),
            self.perm('add'),
            self.perm('open'),
            self.perm('closed')
        })
    
    def test_get_all_permissions__super_user(self):
        """
        Test PermissionsMixin.get_all_permissions() correctly subjects
        superusers to the same object-level permission logic as a standard user
        (they simply don't require the model-level permission be granted to
        them explicitly).
        """
        
        user = self.UserModel.objects.create_user('super')
        user.is_superuser = True
        user.save()
        
        # The user deliberately does not have any model-level permissions to
        # ensure it is the super-ness that grants them model-level permission
        
        obj = self.TestModel.objects.create()
        
        self.assertEqual(user.get_all_permissions(obj), {
            self.perm('delete'),
            self.perm('change'),
            self.perm('add'),
            self.perm('open'),
            self.perm('closed')
        })


class PermissionRequiredDecoratorTestCase(TestCase):
    
    #
    # The impact of altering the DJEM_DEFAULT_403 setting cannot be tested as
    # it is read at time of import of permission_required, so any test-based
    # setting override is not recognised.
    #
    
    def setUp(self):
        
        user = get_user_model().objects.create_user('test1')
        
        # Only grant a limited subset of permissions to test when model-level
        # permissions are NOT granted
        permissions = Permission.objects.filter(
            content_type__app_label='tests',
            content_type__model='olptest',
            codename__in=('open_olptest', 'combined_olptest')
        )
        
        user.user_permissions.set(permissions)
        
        self.user = user
        self.olptest_with_access = OLPTest.objects.create(user=user)
        self.olptest_without_access = OLPTest.objects.create()
        self.factory = RequestFactory()
    
    def test_unauthenticated(self):
        """
        Test the permission_required decorator with an unauthenticated user.
        Ensure the decorator correctly redirects to the login url.
        """
        
        view = permission_required(
            'tests.open_olptest'
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = AnonymousUser()
        
        response = view(request, obj=self.olptest_with_access.pk)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '{0}?next=/test/'.format(settings.LOGIN_URL))
    
    def test_string_arg__access(self):
        """
        Test the permission_required decorator with a valid permission as a
        single string argument.
        Ensure the decorator correctly allows access to the view for a user
        that has been granted that permission at the model level.
        """
        
        view = permission_required(
            'tests.open_olptest'
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request)
        
        self.assertContains(response, 'success', status_code=200)
    
    def test_string_arg__no_access__redirect(self):
        """
        Test the permission_required decorator with a valid permission as a
        single string argument.
        Ensure the decorator correctly denies access to the view for a user
        that has not been granted that permission at the model level, by
        redirecting to the login page.
        """
        
        view = permission_required(
            'tests.add_olptest'
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '{0}?next=/test/'.format(settings.LOGIN_URL))
    
    def test_string_arg__no_access__redirect__custom__relative(self):
        """
        Test the permission_required decorator with a valid permission as a
        single string argument and a custom ``login_url`` is given as a
        relative url.
        Ensure the decorator correctly denies access to the view for a user
        that has not been granted that permission at the model level, by
        redirecting to a custom page specified by the decorator.
        """
        
        view = permission_required(
            'tests.add_olptest',
            login_url='/custom/login/'
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/custom/login/?next=/test/'.format(settings.LOGIN_URL))
    
    def test_string_arg__no_access__redirect__custom__absolute(self):
        """
        Test the permission_required decorator with a valid permission as a
        single string argument and a custom ``login_url`` is given as an
        absolute url.
        Ensure the decorator correctly denies access to the view for a user
        that has not been granted that permission at the model level, by
        redirecting to a custom page specified by the decorator.
        """
        
        view = permission_required(
            'tests.add_olptest',
            login_url='https://example.com/custom/login/'
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            'https://example.com/custom/login/?next=http%3A//testserver/test/'.format(
                settings.LOGIN_URL
            )
        )
    
    def test_string_arg__no_access__raise(self):
        """
        Test the permission_required decorator with a valid permission as a
        single string argument and ``raise_exception`` given as True.
        Ensure the decorator correctly denies access to the view for a user
        that has not been granted that permission at the model level, by
        raising PermissionDenied (which would be translated into a 403 error page).
        """
        
        view = permission_required(
            'tests.add_olptest',
            raise_exception=True
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        with self.assertRaises(PermissionDenied):
            view(request)
    
    def test_string_arg__invalid_perm(self):
        """
        Test the permission_required decorator with an invalid permission as a
        single string argument.
        Ensure the decorator correctly denies access to the view.
        """
        
        view = permission_required(
            'fail'
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '{0}?next=/test/'.format(settings.LOGIN_URL))
    
    def test_tuple_arg__access(self):
        """
        Test the permission_required decorator with a valid permission as a
        single tuple argument.
        Ensure the decorator correctly allows access to the view for a user
        that has been granted that permission at the object level.
        """
        
        view = permission_required(
            ('tests.combined_olptest', 'obj')
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request, obj=self.olptest_with_access.pk)
        
        self.assertContains(response, 'success', status_code=200)
    
    def test_tuple_arg__no_access__redirect(self):
        """
        Test the permission_required decorator with a valid permission as a
        single tuple argument.
        Ensure the decorator correctly denies access to the view for a user
        that has not been granted that permission at the object level, by
        redirecting to the login page.
        """
        
        view = permission_required(
            ('tests.combined_olptest', 'obj')
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request, obj=self.olptest_without_access.pk)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '{0}?next=/test/'.format(settings.LOGIN_URL))
    
    def test_tuple_arg__no_access__redirect__custom(self):
        """
        Test the permission_required decorator with a valid permission as a
        single tuple argument and a custom ``login_url`` given.
        Ensure the decorator correctly denies access to the view for a user
        that has not been granted that permission at the object level, by
        redirecting to a custom page specified by the decorator.
        """
        
        view = permission_required(
            ('tests.combined_olptest', 'obj'),
            login_url='/custom/login/'
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request, obj=self.olptest_without_access.pk)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/custom/login/?next=/test/')
    
    def test_tuple_arg__no_access__raise(self):
        """
        Test the permission_required decorator with a valid permission as a
        single tuple argument and ``raise_exception`` given as True.
        Ensure the decorator correctly denies access to the view for a user
        that has not been granted that permission at the object level, by
        raising PermissionDenied (which would be translated into a 403 error page).
        """
        
        view = permission_required(
            ('tests.combined_olptest', 'obj'),
            raise_exception=True
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        with self.assertRaises(PermissionDenied):
            view(request, obj=self.olptest_without_access.pk)
    
    def test_tuple_arg__invalid_perm(self):
        """
        Test the permission_required decorator with an invalid permission as a
        single tuple argument.
        Ensure the decorator correctly denies access to the view.
        """
        
        view = permission_required(
            ('fail', 'obj')
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request, obj=self.olptest_with_access.pk)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '{0}?next=/test/'.format(settings.LOGIN_URL))
    
    def test_tuple_arg__invalid_object(self):
        """
        Test the permission_required decorator with a valid permission as a
        single tuple argument.
        Ensure the decorator correctly raises a Http404 exception when an
        invalid object primary key is provided (which would be translated into
        a 404 error page).
        """
        
        view = permission_required(
            ('tests.combined_olptest', 'obj')
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        with self.assertRaises(Http404):
            view(request, obj=0)
    
    def test_multiple_args__access_all(self):
        """
        Test the permission_required decorator with multiple valid permissions
        as a mixture of string and tuple arguments.
        Ensure the decorator correctly allows access to the view for a user
        that has all appropriate permissions.
        """
        
        view = permission_required(
            'tests.open_olptest',
            ('tests.combined_olptest', 'obj')
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request, obj=self.olptest_with_access.pk)
        
        self.assertContains(response, 'success', status_code=200)
    
    def test_multiple_args__no_access__model(self):
        """
        Test the permission_required decorator with multiple valid permissions
        as a mixture of string and tuple arguments.
        Ensure the decorator correctly denies access to the view for a user
        that has is missing one of the model-level permissions, by redirecting
        to the login page.
        """
        
        view = permission_required(
            'tests.add_olptest',
            ('tests.combined_olptest', 'obj')
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request, obj=self.olptest_with_access.pk)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '{0}?next=/test/'.format(settings.LOGIN_URL))
    
    def test_multiple_args__no_access__object(self):
        """
        Test the permission_required decorator with multiple valid permissions
        as a mixture of string and tuple arguments.
        Ensure the decorator correctly denies access to the view for a user
        that has is missing one of the object-level permissions, by redirecting
        to the login page.
        """
        
        view = permission_required(
            'tests.open_olptest',
            ('tests.combined_olptest', 'obj')
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request, obj=self.olptest_without_access.pk)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '{0}?next=/test/'.format(settings.LOGIN_URL))
    
    def test_multiple_args__no_access__custom_redirect(self):
        """
        Test the permission_required decorator with multiple valid permissions
        as a mixture of string and tuple arguments, and a custom ``login_url``
        given.
        Ensure the decorator correctly denies access to the view for a user
        that has is missing one of the object-level permissions, by redirecting
        to a custom page specified by the decorator.
        """
        
        view = permission_required(
            'tests.open_olptest',
            ('tests.combined_olptest', 'obj'),
            login_url='/custom/login/'
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request, obj=self.olptest_without_access.pk)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/custom/login/?next=/test/')
    
    def test_multiple_args__no_access__raise(self):
        """
        Test the permission_required decorator with multiple valid permissions
        as a mixture of string and tuple arguments.
        Ensure the decorator correctly denies access to the view for a user
        that has is missing one of the object-level permissions, by raising
        PermissionDenied (which would be translated into a 403 error page).
        """
        
        view = permission_required(
            'tests.open_olptest',
            ('tests.combined_olptest', 'obj'),
            raise_exception=True
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        with self.assertRaises(PermissionDenied):
            view(request, obj=self.olptest_without_access.pk)
    
    def test_multiple_args__invalid_perm(self):
        """
        Test the permission_required decorator with multiple arguments, one
        of which contains an invalid permission.
        Ensure the decorator correctly denies access to the view.
        """
        
        view = permission_required(
            'tests.open_olptest',
            ('fail', 'obj')
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request, obj=self.olptest_with_access.pk)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '{0}?next=/test/'.format(settings.LOGIN_URL))
    
    def test_multiple_args__invalid_object(self):
        """
        Test the permission_required decorator with multiple valid permissions
        as a mixture of string and tuple arguments.
        Ensure the decorator correctly returns a 404 error page when an invalid
        object primary key is provided (which would be translated into a 404
        error page).
        """
        
        view = permission_required(
            'tests.open_olptest',
            ('tests.combined_olptest', 'obj')
        )(_test_view)
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        with self.assertRaises(Http404):
            view(request, obj=0)


class PermissionRequiredMixinTestCase(TestCase):
    
    #
    # The impact of altering the DJEM_DEFAULT_403 setting cannot be tested as
    # it is read at time of import of PermissionRequiredMixin, so any test-based
    # setting override is not recognised.
    #
    
    def setUp(self):
        
        user = get_user_model().objects.create_user('test1')
        
        # Only grant a limited subset of permissions to test when model-level
        # permissions are NOT granted
        permissions = Permission.objects.filter(
            content_type__app_label='tests',
            content_type__model='olptest',
            codename__in=('open_olptest', 'combined_olptest')
        )
        
        user.user_permissions.set(permissions)
        
        self.user = user
        self.olptest_with_access = OLPTest.objects.create(user=user)
        self.olptest_without_access = OLPTest.objects.create()
        self.factory = RequestFactory()
    
    def test_no_permissions(self):
        """
        Test the PermissionRequiredMixin with no defined permission_required.
        Ensure the mixin raises ImproperlyConfigured.
        """
        
        view = _TestView.as_view()
        
        request = self.factory.get('/test/')
        request.user = AnonymousUser()
        
        with self.assertRaises(ImproperlyConfigured):
            view(request)
    
    def test_unauthenticated(self):
        """
        Test the PermissionRequiredMixin with an unauthenticated user.
        Ensure the mixin correctly denies access to the view (the
        unauthenticated user having no permissions).
        """
        
        view = _TestView.as_view(
            permission_required='tests.open_olptest'
        )
        
        request = self.factory.get('/test/')
        request.user = AnonymousUser()
        
        response = view(request, obj=self.olptest_with_access.pk)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '{0}?next=/test/'.format(settings.LOGIN_URL))
    
    def test_string_arg__access(self):
        """
        Test the PermissionRequiredMixin with a valid permission as a single
        string.
        Ensure the mixin correctly allows access to the view for a user that
        has been granted that permission at the model level.
        """
        
        view = _TestView.as_view(
            permission_required='tests.open_olptest'
        )
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request)
        
        self.assertContains(response, 'success', status_code=200)
    
    def test_string_arg__no_access__redirect(self):
        """
        Test the PermissionRequiredMixin with a valid permission as a single
        string.
        Ensure the mixin correctly denies access to the view for a user that
        has not been granted that permission at the model level, by redirecting
        to the login page.
        """
        
        view = _TestView.as_view(
            permission_required='tests.add_olptest'
        )
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '{0}?next=/test/'.format(settings.LOGIN_URL))
    
    def test_string_arg__no_access__redirect__custom(self):
        """
        Test the PermissionRequiredMixin with a valid permission as a single
        string and a custom ``login_url``.
        Ensure the mixin correctly denies access to the view for a user that
        has not been granted that permission at the model level, by redirecting
        to a custom page specified by ``login_url``.
        """
        
        view = _TestView.as_view(
            permission_required='tests.add_olptest',
            login_url='/custom/login/'
        )
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/custom/login/?next=/test/'.format(settings.LOGIN_URL))
    
    def test_string_arg__no_access__raise(self):
        """
        Test the PermissionRequiredMixin with a valid permission as a single
        string and a ``raise_exception`` set to True.
        Ensure the mixin correctly denies access to the view for a user that
        has not been granted that permission at the model level, by raising
        PermissionDenied (which would be translated into a 403 error page).
        """
        
        view = _TestView.as_view(
            permission_required='tests.add_olptest',
            raise_exception=True
        )
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        with self.assertRaises(PermissionDenied):
            view(request)
    
    def test_string_arg__invalid_perm(self):
        """
        Test the PermissionRequiredMixin with an invalid permission as a single
        string.
        Ensure the mixin correctly denies access to the view.
        """
        
        view = _TestView.as_view(
            permission_required='fail'
        )
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '{0}?next=/test/'.format(settings.LOGIN_URL))
    
    def test_tuple_arg__access(self):
        """
        Test the PermissionRequiredMixin with a valid permission as a tuple.
        Ensure the mixin correctly allows access to the view for a user that
        has been granted that permission at the object level.
        """
        
        view = _TestView.as_view(
            permission_required=[('tests.combined_olptest', 'obj')]
        )
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request, obj=self.olptest_with_access.pk)
        
        self.assertContains(response, 'success', status_code=200)
    
    def test_tuple_arg__no_access__redirect(self):
        """
        Test the PermissionRequiredMixin with a valid permission as a tuple.
        Ensure the mixin correctly denies access to the view for a user that
        has not been granted that permission at the object level, by
        redirecting to the login page.
        """
        
        view = _TestView.as_view(
            permission_required=[('tests.combined_olptest', 'obj')]
        )
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request, obj=self.olptest_without_access.pk)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '{0}?next=/test/'.format(settings.LOGIN_URL))
    
    def test_tuple_arg__no_access__redirect__custom(self):
        """
        Test the PermissionRequiredMixin with a valid permission as a tuple and
        a custom ``login_url``.
        Ensure the mixin correctly denies access to the view for a user that
        has not been granted that permission at the object level, by
        to a custom page specified by ``login_url``.
        """
        
        view = _TestView.as_view(
            permission_required=[('tests.combined_olptest', 'obj')],
            login_url='/custom/login/'
        )
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request, obj=self.olptest_without_access.pk)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/custom/login/?next=/test/')
    
    def test_tuple_arg__no_access__raise(self):
        """
        Test the PermissionRequiredMixin with a valid permission as a tuple and
        ``raise_exception`` set to True.
        Ensure the mixin correctly denies access to the view for a user that
        has not been granted that permission at the object level, by raising
        PermissionDenied (which would be translated into a 403 error page).
        """
        
        view = _TestView.as_view(
            permission_required=[('tests.combined_olptest', 'obj')],
            raise_exception=True
        )
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        with self.assertRaises(PermissionDenied):
            view(request, obj=self.olptest_without_access.pk)
    
    def test_tuple_arg__invalid_perm(self):
        """
        Test the PermissionRequiredMixin with an invalid permission as a tuple.
        Ensure the mixin correctly denies access to the view.
        """
        
        view = _TestView.as_view(
            permission_required=[('fail', 'obj')]
        )
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request, obj=self.olptest_with_access.pk)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '{0}?next=/test/'.format(settings.LOGIN_URL))
    
    def test_tuple_arg__invalid_object(self):
        """
        Test the PermissionRequiredMixin with a valid permission as a tuple.
        Ensure the mixin correctly raises a Http404 exception when an
        invalid object primary key is provided (which would be translated into
        a 404 error page).
        """
        
        view = _TestView.as_view(
            permission_required=[('tests.combined_olptest', 'obj')]
        )
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        with self.assertRaises(Http404):
            view(request, obj=0)
    
    def test_multiple_args__access_all(self):
        """
        Test the PermissionRequiredMixin with multiple valid permissions as a
        mixture of strings and tuples.
        Ensure the mixin correctly allows access to the view for a user that
        has all appropriate permissions.
        """
        
        view = _TestView.as_view(
            permission_required=['tests.open_olptest', ('tests.combined_olptest', 'obj')]
        )
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request, obj=self.olptest_with_access.pk)
        
        self.assertContains(response, 'success', status_code=200)
    
    def test_multiple_args__no_access__model(self):
        """
        Test the PermissionRequiredMixin with multiple valid permissions as a
        mixture of strings and tuples.
        Ensure the mixin correctly denies access to the view for a user that
        is missing one of the model-level permissions, by redirecting to the
        login page.
        """
        
        view = _TestView.as_view(
            permission_required=['tests.add_olptest', ('tests.combined_olptest', 'obj')]
        )
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request, obj=self.olptest_with_access.pk)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '{0}?next=/test/'.format(settings.LOGIN_URL))
    
    def test_multiple_args__no_access__object(self):
        """
        Test the PermissionRequiredMixin with multiple valid permissions as a
        mixture of string and tuple arguments.
        Ensure the mixin correctly denies access to the view for a user that
        is missing one of the object-level permissions, by redirecting to the
        login page.
        """
        
        view = _TestView.as_view(
            permission_required=['tests.open_olptest', ('tests.combined_olptest', 'obj')]
        )
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request, obj=self.olptest_without_access.pk)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '{0}?next=/test/'.format(settings.LOGIN_URL))
    
    def test_multiple_args__no_access__custom_redirect(self):
        """
        Test the PermissionRequiredMixin with multiple valid permissions as a
        mixture of string and tuple arguments, and a custom ``login_url``.
        Ensure the mixin correctly denies access to the view for a user that
        is missing one of the object-level permissions, by redirecting to a
        custom page specified by ``login_url``.
        """
        
        view = _TestView.as_view(
            permission_required=['tests.open_olptest', ('tests.combined_olptest', 'obj')],
            login_url='/custom/login/'
        )
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request, obj=self.olptest_without_access.pk)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/custom/login/?next=/test/')
    
    def test_multiple_args__no_access__raise(self):
        """
        Test the PermissionRequiredMixin with multiple valid permissions as a
        mixture of string and tuple arguments, and ``raise_exception`` set to True.
        Ensure the mixin correctly denies access to the view for a user that is
        missing one of the object-level permissions, by raising PermissionDenied
        (which would be translated into a 403 error page).
        """
        
        view = _TestView.as_view(
            permission_required=['tests.open_olptest', ('tests.combined_olptest', 'obj')],
            raise_exception=True
        )
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        with self.assertRaises(PermissionDenied):
            view(request, obj=self.olptest_without_access.pk)
    
    def test_multiple_args__invalid_perm(self):
        """
        Test the PermissionRequiredMixin with multiple permissions as a mixture
        of strings and tuples, one of which is invalid.
        Ensure the mixin correctly denies access to the view.
        """
        
        view = _TestView.as_view(
            permission_required=['tests.open_olptest', ('fail', 'obj')]
        )
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        response = view(request, obj=self.olptest_with_access.pk)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '{0}?next=/test/'.format(settings.LOGIN_URL))
    
    def test_multiple_args__invalid_object(self):
        """
        Test the PermissionRequiredMixin with multiple valid permissions as a
        mixture of strings and tuples.
        Ensure the mixin correctly raises a Http404 exception when an
        invalid object primary key is provided (which would be translated into
        a 404 error page).
        """
        
        view = _TestView.as_view(
            permission_required=['tests.open_olptest', ('tests.combined_olptest', 'obj')]
        )
        
        request = self.factory.get('/test/')
        request.user = self.user  # simulate login
        
        with self.assertRaises(Http404):
            view(request, obj=0)
