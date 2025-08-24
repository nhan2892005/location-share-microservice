package com.locationapp.auth.service;

import com.locationapp.auth.dto.*;
import com.locationapp.auth.entity.User;
import com.locationapp.auth.repository.UserRepository;
import com.locationapp.auth.security.JwtTokenProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import java.time.LocalDateTime;
import java.util.concurrent.TimeUnit;

@Service
public class AuthService {

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private PasswordEncoder passwordEncoder;

    @Autowired
    private JwtTokenProvider jwtTokenProvider;

    @Autowired
    private RedisTemplate<String, String> redisTemplate;

    public AuthResponse register(RegisterRequest request) {
        if (userRepository.existsByUsername(request.getUsername())) {
            throw new RuntimeException("Username already exists");
        }
        if (userRepository.existsByEmail(request.getEmail())) {
            throw new RuntimeException("Email already exists");
        }

        User user = new User(
            request.getUsername(),
            request.getEmail(),
            passwordEncoder.encode(request.getPassword())
        );
        user.setFirstName(request.getFirstName());
        user.setLastName(request.getLastName());
        
        user = userRepository.save(user);

        String accessToken = jwtTokenProvider.generateAccessToken(user);
        String refreshToken = jwtTokenProvider.generateRefreshToken(user);

        // Store refresh token in Redis
        redisTemplate.opsForValue().set(
            "refresh_token:" + user.getId(),
            refreshToken,
            7, TimeUnit.DAYS
        );

        return new AuthResponse(accessToken, refreshToken, user.getId(), user.getUsername());
    }

    public AuthResponse login(LoginRequest request) {
        User user = userRepository.findByUsernameOrEmail(request.getUsernameOrEmail(), request.getUsernameOrEmail())
            .orElseThrow(() -> new RuntimeException("User not found"));

        if (!passwordEncoder.matches(request.getPassword(), user.getPassword())) {
            throw new RuntimeException("Invalid password");
        }

        user.setLastLogin(LocalDateTime.now());
        userRepository.save(user);

        String accessToken = jwtTokenProvider.generateAccessToken(user);
        String refreshToken = jwtTokenProvider.generateRefreshToken(user);

        redisTemplate.opsForValue().set(
            "refresh_token:" + user.getId(),
            refreshToken,
            7, TimeUnit.DAYS
        );

        return new AuthResponse(accessToken, refreshToken, user.getId(), user.getUsername());
    }

    public AuthResponse refreshToken(String refreshToken) {
        Long userId = jwtTokenProvider.getUserIdFromToken(refreshToken);
        String storedToken = redisTemplate.opsForValue().get("refresh_token:" + userId);
        
        if (storedToken == null || !storedToken.equals(refreshToken)) {
            throw new RuntimeException("Invalid refresh token");
        }

        User user = userRepository.findById(userId)
            .orElseThrow(() -> new RuntimeException("User not found"));

        String newAccessToken = jwtTokenProvider.generateAccessToken(user);
        String newRefreshToken = jwtTokenProvider.generateRefreshToken(user);

        redisTemplate.opsForValue().set(
            "refresh_token:" + user.getId(),
            newRefreshToken,
            7, TimeUnit.DAYS
        );

        return new AuthResponse(newAccessToken, newRefreshToken, user.getId(), user.getUsername());
    }

    public boolean validateToken(String token) {
        return jwtTokenProvider.validateToken(token);
    }

    public void logout(String token) {
        Long userId = jwtTokenProvider.getUserIdFromToken(token);
        redisTemplate.delete("refresh_token:" + userId);
        
        // Add token to blacklist
        long expiration = jwtTokenProvider.getExpirationFromToken(token);
        redisTemplate.opsForValue().set(
            "blacklist:" + token,
            "true",
            expiration - System.currentTimeMillis(),
            TimeUnit.MILLISECONDS
        );
    }

    public UserProfileResponse getUserProfile(String token) {
        Long userId = jwtTokenProvider.getUserIdFromToken(token);
        User user = userRepository.findById(userId)
            .orElseThrow(() -> new RuntimeException("User not found"));

        return new UserProfileResponse(
            user.getId(),
            user.getUsername(),
            user.getEmail(),
            user.getFirstName(),
            user.getLastName(),
            user.getPhoneNumber(),
            user.getRoles(),
            user.getCreatedAt(),
            user.getLastLogin()
        );
    }
}