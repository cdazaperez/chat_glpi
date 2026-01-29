'use client';

import React, { useState } from 'react';
import { MessageSquare, Mail, Building, Shield, LogIn } from 'lucide-react';
import { ChatContext } from '@/types';

interface UserLoginProps {
  onLogin: (context: ChatContext) => void;
  showRoleSelector?: boolean;
}

export function UserLogin({ onLogin, showRoleSelector }: UserLoginProps) {
  // Default to environment variable or true
  const showRoles = showRoleSelector ?? (process.env.NEXT_PUBLIC_SHOW_ROLE_SELECTOR !== 'false');
  const [email, setEmail] = useState('');
  const [department, setDepartment] = useState('');
  const [role, setRole] = useState<'technician' | 'admin'>('technician');
  const [error, setError] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    // Validate email
    if (!email.trim()) {
      setError('Por favor ingresa tu correo electrónico');
      return;
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email.trim())) {
      setError('Por favor ingresa un correo electrónico válido');
      return;
    }

    onLogin({
      user_email: email.trim().toLowerCase(),
      department: department.trim() || undefined,
      user_role: role,
    });
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 p-4">
      <div className="w-full max-w-md">
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-8">
          {/* Header */}
          <div className="flex flex-col items-center mb-8">
            <div className="w-16 h-16 bg-primary-500 rounded-xl flex items-center justify-center mb-4">
              <MessageSquare className="w-8 h-8 text-white" />
            </div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">
              {process.env.NEXT_PUBLIC_APP_TITLE || 'Helpdesk AI'}
            </h1>
            <p className="text-gray-500 dark:text-gray-400 text-center mt-2">
              Inicia sesión para acceder al soporte técnico
            </p>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Email */}
            <div>
              <label
                htmlFor="email"
                className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
              >
                Correo electrónico
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  type="email"
                  id="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="tu.correo@empresa.com"
                  className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  autoComplete="email"
                  autoFocus
                />
              </div>
            </div>

            {/* Department (optional) */}
            <div>
              <label
                htmlFor="department"
                className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
              >
                Departamento <span className="text-gray-400">(opcional)</span>
              </label>
              <div className="relative">
                <Building className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  type="text"
                  id="department"
                  value={department}
                  onChange={(e) => setDepartment(e.target.value)}
                  placeholder="Ej: Tecnología, Ventas, RRHH"
                  className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                />
              </div>
            </div>

            {/* Role selector (optional) */}
            {showRoles && (
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Rol
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setRole('technician')}
                    className={`flex items-center justify-center gap-2 px-4 py-2 rounded-lg border transition-colors ${
                      role === 'technician'
                        ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20 text-primary-700 dark:text-primary-300'
                        : 'border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700'
                    }`}
                  >
                    <Shield className="w-4 h-4" />
                    Técnico
                  </button>
                  <button
                    type="button"
                    onClick={() => setRole('admin')}
                    className={`flex items-center justify-center gap-2 px-4 py-2 rounded-lg border transition-colors ${
                      role === 'admin'
                        ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20 text-primary-700 dark:text-primary-300'
                        : 'border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700'
                    }`}
                  >
                    <Shield className="w-4 h-4" />
                    Admin
                  </button>
                </div>
              </div>
            )}

            {/* Error message */}
            {error && (
              <div className="p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
                <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
              </div>
            )}

            {/* Submit button */}
            <button
              type="submit"
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-primary-600 hover:bg-primary-700 text-white font-medium rounded-lg transition-colors"
            >
              <LogIn className="w-5 h-5" />
              Iniciar Sesión
            </button>
          </form>

          {/* Footer */}
          <p className="mt-6 text-xs text-center text-gray-500 dark:text-gray-400">
            Tu información se usa para identificarte en el sistema GLPI
          </p>
        </div>
      </div>
    </div>
  );
}
