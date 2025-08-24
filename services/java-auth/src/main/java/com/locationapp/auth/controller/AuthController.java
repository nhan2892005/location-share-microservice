package com.locationapp.auth.controller;

import com.locationapp.auth.dto.*;
import com.locationapp.auth.service.AuthService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/auth")
@CrossOrigin(origins = "*")
public class AuthController {

    @Autowired
    private AuthService authService;

    @PostMapping("/register")
    public ResponseEntity<?> register(@Valid @RequestBody RegisterRequest request) {
        try {
            AuthResponse response = authService.register(request);
            return ResponseEntity.ok(response);
        } catch (Exception e) {
            return ResponseEntity.badRequest()
                .body(new ApiResponse(false, e.getMessage()));
        }
    }

    @PostMapping("/login")
    public ResponseEntity<?> login(@Valid @RequestBody LoginRequest request) {
        try {
            AuthResponse response = authService.login(request);
            return ResponseEntity.ok(response);
        } catch (Exception e) {
            return ResponseEntity.badRequest()
                .body(new ApiResponse(false, "Invalid credentials"));
        }
    }

    @PostMapping("/refresh")
    public ResponseEntity<?> refresh(@Valid @RequestBody RefreshTokenRequest request) {
        try {
            AuthResponse response = authService.refreshToken(request.getRefreshToken());
            return ResponseEntity.ok(response);
        } catch (Exception e) {
            return ResponseEntity.badRequest()
                .body(new ApiResponse(false, "Invalid refresh token"));
        }
    }

    @PostMapping("/validate")
    public ResponseEntity<?> validateToken(@RequestHeader("Authorization") String token) {
        try {
            boolean isValid = authService.validateToken(token.replace("Bearer ", ""));
            return ResponseEntity.ok(new ApiResponse(isValid, isValid ? "Token is valid" : "Token is invalid"));
        } catch (Exception e) {
            return ResponseEntity.badRequest()
                .body(new ApiResponse(false, "Invalid token"));
        }
    }

    @PostMapping("/logout")
    public ResponseEntity<?> logout(@RequestHeader("Authorization") String token) {
        try {
            authService.logout(token.replace("Bearer ", ""));
            return ResponseEntity.ok(new ApiResponse(true, "Logged out successfully"));
        } catch (Exception e) {
            return ResponseEntity.badRequest()
                .body(new ApiResponse(false, "Logout failed"));
        }
    }

    @GetMapping("/profile")
    public ResponseEntity<?> getProfile(@RequestHeader("Authorization") String token) {
        try {
            UserProfileResponse profile = authService.getUserProfile(token.replace("Bearer ", ""));
            return ResponseEntity.ok(profile);
        } catch (Exception e) {
            return ResponseEntity.badRequest()
                .body(new ApiResponse(false, "Unable to fetch profile"));
        }
    }
}